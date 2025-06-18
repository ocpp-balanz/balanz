"""
User model. Simple user management.

Users will be stored in a CSV file along with a sha256 hash of their login (username+password).
"""

import csv
import logging
from enum import StrEnum

from audit_logger import audit_logger
from config import config
from util import gen_sha_256

# Logging setup
logger = logging.getLogger("user")


class UserType(StrEnum):
    """User types.

    A user type combines the available API methods with the available UI screens/focus.
    """

    # ReadOnly types:
    status = "Status"
    analysis = "Analysis"

    # Overwrite session priority
    session_priority = "SessionPriority"

    # Maintain tags
    tag = "Tags"

    # Everything
    admin = "Admin"


# Forward declaration
class User:
    pass


# ---------------------------
# Classes - Implementation
# ---------------------------
class User:
    """
    User represents the simple user.
    """

    # Static dictionary of Sessions. Key is a generated session_id.
    user_list: dict[User] = {}

    def __init__(
        self,
        user_id: str,
        password: str = None,
        user_type: UserType = None,
        description: str = "",
        auth_sha: str = None,
    ) -> None:
        """Init"""
        self.user_id: str = user_id
        self.auth_sha: str = auth_sha
        self.description: str = description
        self.user_type: UserType = user_type if user_type else UserType.status
        if auth_sha is None and password is not None:
            self.auth_sha = gen_sha_256(user_id + password)
        # Ignore if already there
        if self.user_id not in User.user_list:
            User.user_list[self.user_id] = self

    def update(self, password: str = None, user_type: UserType = None, description: str = None) -> None:
        """Update specified values on an existing user"""
        if password is not None:
            self.auth_sha = gen_sha_256(self.user_id + password)
        if user_type is not None:
            self.user_type = user_type
        if description is not None:
            self.description = description

    def external(self) -> str:
        fields = ["user_id", "user_type", "description"]
        result = {k: self.__dict__[k] for k in fields}
        return result

    @staticmethod
    def check_auth(auth: str) -> UserType:
        """Check auth (typically user_id and password concatenated) against stored sha.

        Returns user_type or None if no match found."""
        auth_sha: str = gen_sha_256(auth)
        for user in User.user_list.values():
            if user.auth_sha == auth_sha:
                logger.info(f"Successful auth check. User {user.user_id}, type {user.user_type}")
                return user.user_type
        logger.info(f"Failed auth check. auth starts {auth[:5]}...")
        return None

    @staticmethod
    def read_csv(file: str) -> None:
        """Read users from CSV file

        If called again, will only add new users.

        TODO: Delete case, i.e. if existing users not mentioned in CSV file.

        Assumed format: "user_id","user_type","auth_sha"
        """
        logger.info(f"Reading users from {file}")
        with open(file, mode="r") as file:
            reader = csv.DictReader(file)
            for user in reader:
                if user["user_id"] not in User.user_list:
                    User(
                        user_id=user["user_id"],
                        user_type=user["user_type"],
                        description=user["description"],
                        auth_sha=user["auth_sha"],
                    )

    @staticmethod
    def write_csv(file: str) -> None:
        """Rewrite users to CSV file to reflect changes, i.e. auth_sha set"""
        logger.info(f"Writing users to {file}")
        with open(file, mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["user_id", "user_type", "description", "auth_sha"])
            user: User = None
            for u in User.user_list:
                user = User.user_list[u]
                writer.writerow([user.user_id, user.user_type, user.description, user.auth_sha])
