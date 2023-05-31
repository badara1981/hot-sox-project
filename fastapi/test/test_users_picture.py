from unittest import mock
from fastapi.testclient import TestClient

from sqlalchemy.orm import Session

import warnings
from fastapi_pagination.utils import FastAPIPaginationWarning

warnings.simplefilter("ignore", FastAPIPaginationWarning)

from .inital_test_setup import (
    client,
    PREFIX,
    TEST_USER1,
    TEST_USER2,
    test_db_setup,
    mock_upload_file,
    token,
)


# setup a test database for the test
from api.authentication.hashing import Hash
from api.database.models import User, Sock, MessageMail, MessageChat
from api.database.setup import engine


@mock.patch("api.controller.ctr_user_pic.uploader.upload")
def test_user_upload_profilepic(mock_uploader_upload, test_db_setup):
    with Session(engine) as db:
        username = TEST_USER2["username"]
        password = TEST_USER2["password"]

        # set up the mock return value
        mock_uploader_upload.return_value = {
            "url": "https://cloudinary.com/mock_image.jpg"
        }

        # make a test user
        db_user = db.query(User).filter(User.username == username).first()

        # send a request to add a profile picture
        with open("./requirements.txt", "rb") as mock_file:
            response = client.post(
                f"{PREFIX}/user/profilepic/",
                files={"file": ("filename", mock_file)},
                headers=token(username="testuser2", password="testuser2"),
            )

        # check that the response is what we expect
        assert response.status_code == 201
        assert (
            response.json()["profile_picture"]
            == "https://cloudinary.com/mock_image.jpg"
        )

        # check that the user in the database has the new profile picture
        db_user = db.query(User).filter(User.username == username).first()
        assert len(db_user.profile_pictures) == 1
        assert (
            db_user.profile_pictures[0].profile_picture
            == "https://cloudinary.com/mock_image.jpg"
        )


@mock.patch("api.database.models.destroy_profilepicture_on_cloud")
@mock.patch("api.database.models.uploader.destroy")
@mock.patch("api.controller.ctr_user_pic.uploader.upload")
def test_user_delete_profilepic(
    mock_uploader_upload,
    mock_uploader_destroy,
    mock_celery,
    test_db_setup,
):
    with Session(engine) as db:
        username = TEST_USER2["username"]
        password = TEST_USER2["password"]

        # set up the mock return value
        mock_uploader_upload.return_value = {
            "url": "https://cloudinary.com/mock_image.jpg"
        }
        mock_uploader_destroy.return_value = True
        mock_celery.return_value = {"message": f"user profile picture was deleted"}

        # make a test user
        db_user = db.query(User).filter(User.username == username).first()

        # send a request to add a profile picture
        with open("./requirements.txt", "rb") as mock_file:
            response = client.post(
                f"{PREFIX}/user/profilepic",
                files={"file": ("filename", mock_file)},
                headers=token(username="testuser2", password="testuser2"),
            )

        # make a test user and get all pictures
        db_user = db.query(User).filter(User.username == TEST_USER2["username"]).first()
        before_delete_profilepics = db_user.profile_pictures

        # send a request to delete a profile picture
        response = client.request(
            "DELETE",
            f"{PREFIX}/user/profilepic/{before_delete_profilepics[0].id}",
            headers=token("testuser2", "testuser2"),
        )

        # check that the response is what is expect
        assert response.status_code == 204

    # new session to persist changes of transactions before!
    with Session(engine) as db:
        # check that the user in the database has the new profile picture
        db_user_new = (
            db.query(User).filter(User.username == TEST_USER2["username"]).first()
        )
        assert len(db_user_new.profile_pictures) == len(before_delete_profilepics) - 1
