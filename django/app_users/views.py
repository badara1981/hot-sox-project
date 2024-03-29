from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.db.models import Q
from django.views.generic import TemplateView

from .validator import HotSoxLogInAndValidationCheckMixin, ProtectedSockMixin
from app_geo.utilities import GeoLocation, GeoMap
from .models import (
    User,
    UserProfilePicture,
    Sock,
    SockProfilePicture,
    UserMatch,
    MessageChat,
)
from .forms import (
    UserSignUpForm,
    UserProfileForm,
    UserProfilePictureForm,
    SockProfileForm,
    SockProfilePictureForm,
)

from allauth.account.views import SignupView
from app_mail.tasks import celery_send_mail


def validate_sock_ownership(request, valid_sock=None, picture_pk=None):
    # if picture is set
    if picture_pk:
        if int(picture_pk) in [picture.pk for picture in valid_sock.get_all_pictures()]:
            return True
        return False

    # if only sock object is set
    if valid_sock and valid_sock.user == request.user:
        return True

    return False


class UserSignUp(SignupView):
    """Custom UserSingUpView
    - add request object to the form
    - create user
    - add geolocation before saving to db (Using signals in models)
    """

    form_class = UserSignUpForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs


class UserProfileDetails(HotSoxLogInAndValidationCheckMixin, TemplateView):
    """View to show a user's details."""

    model = User
    template_name = "users/profile_details.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # include the current user in the context
        user = get_object_or_404(User, pk=self.request.user.pk)
        context["user"] = user
        context["user_detail"] = user.to_json()

        # include the geo information in the context
        lat = user.location_latitude
        lng = user.location_longitude
        city = user.location_city
        if city and lat and lng:
            context["map"] = GeoMap.get_geo_map(
                map_width="100%",
                map_height="100%",
                geo_location_a=(lat, lng),
                geo_location_b=(lat, lng),
                city_location=city,
            )

        context["left_arrow_go_to_url"] = ""  # reverse("app_home:index")
        context["right_arrow_go_to_url"] = reverse("app_users:user-profile-update")
        return context


class UserProfileUpdate(LoginRequiredMixin, TemplateView):
    """View to edit details of a user.
    We will gather information from from.UserSignUpForm
    we  store this user to the db via ORM and try to
    login() then user!
    This View is not protected by the HotSoxLogInAndValidationCheckMixin!
    It needs to be available for users who are not validated!
    """

    model = User
    template_name = "users/profile_update.html"

    def post(self, request, *args, **kwargs):
        user_to_update = get_object_or_404(User, pk=request.user.pk)
        form_user_profile = UserProfileForm(request.POST, instance=user_to_update)

        if form_user_profile.is_valid():
            # update the user to the database
            user_to_update = form_user_profile.save(commit=False)
            # fix the data
            user_to_update.first_name = form_user_profile.cleaned_data[
                "first_name"
            ].title()
            user_to_update.last_name = form_user_profile.cleaned_data[
                "last_name"
            ].title()
            # set geo location
            try:
                (
                    user_to_update.location_latitude,
                    user_to_update.location_longitude,
                ) = GeoLocation.get_geolocation_from_city(user_to_update.location_city)
            except:
                user_to_update.location_latitude = 0
                user_to_update.location_longitude = 0
            # store the user to the database
            user_to_update.save()
            messages.success(request, "Profile details successfully updated.")
            # log user in via django login
            login(request, user_to_update)
            # redirect to user profile details page
            return redirect(reverse("app_users:user-profile-details"))
        # in case of invalid go here
        messages.warning(request, "Profile details could not be updated.")
        return render(
            request,
            "users/profile_update.html",
            {
                "form_user_profile": form_user_profile,
                "left_arrow_go_to_url": reverse("app_users:user-profile-details"),
                "right_arrow_go_to_url": reverse("app_users:sock-overview"),
            },
        )

    def get(self, request, *args, **kwargs):
        user_to_update = get_object_or_404(User, pk=request.user.pk)

        # get geo location from IP if not set
        if not user_to_update.location_city:
            try:
                city, _, _ = GeoLocation.get_geolocation_from_ip(
                    GeoLocation.get_ip_address(request)
                )
            except:
                city = {"city": ""}
            user_to_update.location_city = city["city"]

        form_user_profile = UserProfileForm(instance=user_to_update)

        # show user profile update page
        return render(
            request,
            "users/profile_update.html",
            {
                "form_user_profile": form_user_profile,
                "left_arrow_go_to_url": reverse("app_users:user-profile-details"),
                "right_arrow_go_to_url": reverse("app_users:sock-overview"),
            },
        )


class UserProfileDelete(HotSoxLogInAndValidationCheckMixin, TemplateView):
    """View to delete the user profile and all related details"""

    def get(self, request, *args, **kwargs):
        # get current user
        user = request.user
        # send email about account deletion
        celery_send_mail.delay(
            recipient_list=[user.email],
            notification=user.notification,
            email_subject="HotSox Account Deletion",
            email_message="Your HotSox account has been deleted. We are very sorry to see you go :(",
        )
        # delete user
        user.delete()
        # logout
        logout(request)
        # return to login site plus message
        messages.success(
            request, "Profile successfully deleted. Sorry to see you go :("
        )
        return redirect(reverse("account_login"))


class UserProfilePictureUpdate(HotSoxLogInAndValidationCheckMixin, TemplateView):
    """View to edit/add a new profile picture to a user."""

    model = User
    template_name = "users/profile_picture.html"

    def post(self, request, *args, **kwargs):
        # get current user
        user_to_update = get_object_or_404(User, pk=request.user.pk)
        # get all profile pictures from current user
        profile_picture_query_set = user_to_update.get_all_pictures()

        # check if profile_picture_query_set is not True
        if not profile_picture_query_set:
            profile_picture_query_set = [""]

        if request.POST.get("method") == "delete":
            # delete the selected picture!
            picture_pk = request.POST.get("picture_pk", None)
            if picture_pk:
                # validate that the picture_pk is part of the users profile pictures
                if int(picture_pk) in [
                    picture.pk for picture in request.user.get_all_pictures()
                ]:
                    UserProfilePicture_obj = UserProfilePicture.objects.get(
                        pk=picture_pk
                    )
                    UserProfilePicture_obj.delete()
                messages.success(request, "Profile picture successfully deleted.")
                return redirect(reverse("app_users:user-profile-picture"))

        elif request.POST.get("method") == "add":
            # add the selected picture!
            form_user_profile_picture = UserProfilePictureForm(
                request.POST,
                request.FILES,
                initial={"user": user_to_update},
            )
            if form_user_profile_picture.is_valid():
                # create a profile_picture object
                new_profile_picture = form_user_profile_picture.save(commit=False)
                # set one to many field [user] to current user
                new_profile_picture.user = user_to_update
                # store the picture to the database
                new_profile_picture.save()
                # redirect to user profile details page
                messages.success(request, "Profile picture successfully updated.")
                return redirect(reverse("app_users:user-profile-picture"))
            # in case of invalid go here
            messages.warning(request, "Profile picture could not be updated.")
            return redirect(reverse("app_users:user-profile-picture"))

    def get(self, request, *args, **kwargs):
        # get current user
        user_to_update = get_object_or_404(User, pk=request.user.pk)
        # get all profile pictures from current user
        profile_picture_query_set = user_to_update.get_all_pictures()
        # create form
        form_user_profile_picture = UserProfilePictureForm(
            initial={
                "user": user_to_update,
            },
        )

        # show user profile picture page
        return render(
            request,
            "users/profile_picture.html",
            {
                "profile_picture_query_set": profile_picture_query_set,
                "form_user_profile_picture": form_user_profile_picture,
                "left_arrow_go_to_url": "",
                "right_arrow_go_to_url": reverse("app_users:user-profile-details"),
            },
        )


class SockProfileOverview(HotSoxLogInAndValidationCheckMixin, TemplateView):
    """View to show all socks's of a User."""

    model = User
    template_name = "users/sock_overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["left_arrow_go_to_url"] = reverse("app_users:user-profile-update")
        context["right_arrow_go_to_url"] = ""
        return context

    def post(self, request, *args, **kwargs):
        # check if delete or add

        if request.POST.get("method") == "delete":
            # delete the selected sock!
            sock_pk = request.POST.get("sock_pk", None)

            if sock_pk:
                sock_obj = get_object_or_404(Sock, pk=sock_pk)
                # validate that the user have the right to alter the sock
                if validate_sock_ownership(request, valid_sock=sock_obj):
                    sock_obj.delete()
                    if sock_pk == request.session.get("sock_pk", None):
                        request.session["sock_pk"] = None
                # return back to sock overview
                messages.success(request, "Sock successfully deleted.")
                return redirect(reverse("app_users:sock-overview"))

        elif request.POST.get("method") == "add":
            # redirect to sock creation
            return redirect(reverse("app_users:sock-create"))
        messages.warning(request, "Something went wrong.")
        return redirect(reverse("app_users:sock-overview"))


class SockSelection(HotSoxLogInAndValidationCheckMixin, TemplateView):
    model = User
    template_name = None

    def post(self, request, *args, **kwargs):
        # register selected sock in the current session
        if request.POST.get("sock_pk", None):
            request.session["sock_pk"] = request.POST.get("sock_pk")

        redirect_url = request.POST.get("redirect_url", None)

        # add specific routes to redirect to here
        if request.session.get("redirect_url", None) == reverse("app_home:swipe"):
            request.session["redirect_url"] = None
            return redirect(reverse("app_home:swipe"))
        if redirect_url == reverse("app_users:sock-details"):
            return redirect(reverse("app_users:sock-details"))
        if redirect_url == reverse("app_users:sock-picture"):
            return redirect(reverse("app_users:sock-picture"))

        # Get the URL of the previous page
        prev_url = request.META.get("HTTP_REFERER")
        # Redirect the user back to the previous page
        return HttpResponseRedirect(prev_url)


class SockProfileCreate(HotSoxLogInAndValidationCheckMixin, TemplateView):
    """Add a new sock.
    We will gather information from from.SockForm
    Next store this sock to the db via ORM"""

    model = Sock
    template_name = "users/sock_update.html"

    def get(self, request):
        form_sock_profile = SockProfileForm(initial={"user": request.user})

        # show sock profile update page
        return render(
            request,
            "users/sock_update.html",
            {
                "form_sock_profile": form_sock_profile,
                "sock": "",
                "left_arrow_go_to_url": reverse("app_users:sock-overview"),
                "right_arrow_go_to_url": "",
            },
        )

    def post(self, request):
        form_sock_profile = SockProfileForm(
            request.POST, initial={"user": request.user}
        )

        if form_sock_profile.is_valid():
            # store the sock to the database
            sock_to_add = form_sock_profile.save(commit=False)
            sock_to_add.user = request.user
            sock_to_add.save()
            # register current sock to the session
            request.session["sock_pk"] = sock_to_add.pk
            # redirect to sock profile details page
            messages.success(
                request, f"{sock_to_add.info_name} successfully added to your socks."
            )
            return redirect(reverse("app_users:sock-picture"))
        # in case of invalid go here
        return redirect(reverse("app_users:sock-create"))


class SockProfileDetails(
    ProtectedSockMixin, HotSoxLogInAndValidationCheckMixin, TemplateView
):
    """View to show a socks's details."""

    model = Sock
    template_name = "users/sock_details.html"

    def get(self, request, *args, **kwargs):
        context = {}
        context["left_arrow_go_to_url"] = reverse("app_users:sock-overview")
        context["right_arrow_go_to_url"] = reverse("app_users:sock-update")
        context["sock"] = get_object_or_404(Sock, pk=request.session.get("sock_pk"))
        return render(request, "users/sock_details.html", context)


class SockProfileUpdate(
    ProtectedSockMixin, HotSoxLogInAndValidationCheckMixin, TemplateView
):
    """View to edit a sock.
    We will gather information from from.SockForm
    Next store this sock to the db via ORM
    """

    model = Sock
    template_name = "users/sock_update.html"

    def post(self, request):
        sock_to_update = get_object_or_404(Sock, pk=request.session.get("sock_pk"))
        form_sock_profile = SockProfileForm(request.POST, instance=sock_to_update)

        if form_sock_profile.is_valid():
            # store the sock to the database
            sock_to_update = form_sock_profile.save()
            # redirect to sock profile details page
            messages.success(
                request, f"{sock_to_update.info_name} successfully updated."
            )
            return redirect(reverse("app_users:sock-details"))
        # in case of invalid go here
        return redirect(reverse("app_users:sock-update"))

    def get(self, request):
        sock_to_update = get_object_or_404(Sock, pk=request.session.get("sock_pk"))
        form_sock_profile = SockProfileForm(instance=sock_to_update)

        # show sock profile update page
        return render(
            request,
            "users/sock_update.html",
            {
                "form_sock_profile": form_sock_profile,
                "sock": sock_to_update,
                "left_arrow_go_to_url": reverse("app_users:sock-details"),
                "right_arrow_go_to_url": "",
            },
        )


class SockProfilePictureUpdate(
    ProtectedSockMixin, HotSoxLogInAndValidationCheckMixin, TemplateView
):
    """View to edit/add a new profile picture to a user."""

    model = Sock
    template_name = "users/sock_picture.html"

    def post(self, request):
        # get current user
        sock_to_update = get_object_or_404(Sock, pk=request.session.get("sock_pk"))
        # get all profile pictures from current user
        profile_picture_query_set = sock_to_update.get_all_pictures()

        # check if profile_picture_query_set is not True
        if not profile_picture_query_set:
            profile_picture_query_set = [""]

        if request.POST.get("method") == "delete":
            # delete the selected picture!
            picture_pk = request.POST.get("picture_pk", None)
            # validate that the picture_pk is part of the socks profile pictures
            if picture_pk and validate_sock_ownership(
                request, valid_sock=sock_to_update, picture_pk=picture_pk
            ):
                SockProfilePicture_obj = SockProfilePicture.objects.get(pk=picture_pk)
                SockProfilePicture_obj.delete()
                messages.success(request, f"profile picture successfully deleted.")
            return redirect(reverse("app_users:sock-picture"))

        elif request.POST.get("method") == "add":
            # add the selected picture!
            form_sock_profile_picture = SockProfilePictureForm(
                request.POST,
                request.FILES,
                initial={"sock": sock_to_update},
            )
            if form_sock_profile_picture.is_valid():
                # create a profile_picture object
                new_profile_picture = form_sock_profile_picture.save(commit=False)
                # set one to many field [user] to current user
                new_profile_picture.sock = sock_to_update
                # store the picture to the database
                new_profile_picture.save()
                # redirect to user profile details page
                messages.success(request, f"profile picture successfully updated.")
                return redirect(reverse("app_users:sock-picture"))
            # in case of invalid go here
            return redirect(reverse("app_users:sock-picture"))

    def get(self, request):
        # get current user
        sock_to_update = get_object_or_404(Sock, pk=request.session.get("sock_pk"))
        # get all profile pictures from current user
        profile_picture_query_set = sock_to_update.get_all_pictures()
        # create form
        form_sock_profile_picture = SockProfilePictureForm(
            initial={
                "sock": sock_to_update,
            },
        )

        # show user profile picture page
        return render(
            request,
            "users/sock_picture.html",
            {
                "profile_picture_query_set": profile_picture_query_set,
                "form_sock_profile_picture": form_sock_profile_picture,
                "sock": sock_to_update,
                "left_arrow_go_to_url": "",
                "right_arrow_go_to_url": reverse("app_users:sock-details"),
            },
        )


class UserMatches(HotSoxLogInAndValidationCheckMixin, TemplateView):
    model = User
    template_name = "users/profile_matches.html"

    def get(self, request):
        user = get_object_or_404(User, pk=request.user.pk)
        user_matches = user.get_matches()
        user_unmatched = user.get_unmatched()
        context = {
            "user": user,
            "user_matches": user_matches,
            "user_unmatched": user_unmatched,
        }
        return render(request, "users/profile_matches.html", context)


class UserMatchProfileDetails(HotSoxLogInAndValidationCheckMixin, TemplateView):
    """View to show a matched user's details."""

    model = User
    template_name = None

    def get(self, request, **kwargs):
        # get current user
        current_user = request.user
        # get matched user from urls
        try:
            match_user = User.objects.get(username=kwargs.get("username", None))
        except User.DoesNotExist:
            return redirect(reverse("app_users:user-matches"))

        # validate is match exists
        matches = UserMatch.objects.filter(
            Q(user=current_user, other=match_user)
            | Q(user=match_user, other=current_user)
        )
        if not matches:
            return redirect(reverse("app_users:user-matches"))

        # gather the geo information of the current user
        user_lat = current_user.location_latitude
        user_lng = current_user.location_longitude
        user_city = current_user.location_city
        # gather the geo information of the matched user
        match_lat = match_user.location_latitude
        match_lng = match_user.location_longitude
        match_city = match_user.location_city

        # build context
        context = {
            "user": match_user,
            "user_detail": match_user.to_json(),
            "distance": GeoLocation.get_distance(
                (match_lat, match_lng), (user_lat, user_lng)
            ),
            "map": GeoMap.get_geo_map(
                map_width="100",
                map_height="100",
                geo_location_a=(match_lat, match_lng),
                geo_location_b=(user_lat, user_lng),
                city_location=match_city,
                city_destination=user_city,
                add_line=True,
            ),
        }
        # define naviation arrow urls
        context["left_arrow_go_to_url"] = ""
        context["right_arrow_go_to_url"] = ""
        return render(request, "users/match_profile_details.html", context)


class UserMatchDelete(HotSoxLogInAndValidationCheckMixin, TemplateView):
    """View to show a matched user's details."""

    model = User
    template_name = None

    def get(self, request, **kwargs):
        # get current user
        current_user = request.user
        # get matched user from urls
        try:
            match_user = User.objects.get(username=kwargs.get("username", None))
        except User.DoesNotExist:
            return redirect(reverse("user-matches"))

        # validate is match exists
        matches = UserMatch.objects.filter(
            Q(user=current_user, other=match_user)
            | Q(user=match_user, other=current_user)
        )
        if not matches:
            return redirect(reverse("user-matches"))

        # get all the chat messages between the users
        chat_messages = MessageChat.objects.filter(
            Q(user=current_user, other=match_user)
            | Q(user=match_user, other=current_user)
        )
        # delete the chat messages
        for message in chat_messages:
            message.delete()

        # set all the match objects to unmatched = True
        for match in matches:
            match.unmatched = True
            match.save()

        messages.success(
            request, f"match with {match_user.username} successfully deleted."
        )

        # email to confirm deleted match
        match_message = f"The match between {match_user.username} and {current_user.username} has been deleted"
        celery_send_mail.delay(
            email_subject=f"You have unmached with {match_user.username}",
            email_message=match_message,
            recipient_list=[current_user.email],
            notification=current_user.notification,
        )
        celery_send_mail.delay(
            email_subject=f"{current_user.username} has unmached you",
            email_message=match_message,
            recipient_list=[match_user.email],
            notification=match_user.notification,
        )

        # return to match overview
        return redirect(reverse("app_users:user-matches"))
