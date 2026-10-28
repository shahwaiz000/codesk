"""Set a new password for the owner account when the old one is forgotten.

Run it in the backend folder, with the backend stopped:
    python -m app.reset_password

Only someone who can open this computer's CODesk folder can do this, which is the same person
who could open the database file. All saved logins are ended, and the change goes in the activity log."""
import getpass
import sys

from . import audit
from .auth import check_password_rules, hash_password
from .config import settings
from .database import SessionLocal
from .models import LoginSession, User


def reset(db, password: str) -> User:
    user = db.query(User).order_by(User.id).first()
    if not user:
        raise LookupError("There is no account yet. Start CODesk and create one on the first page")
    problem = check_password_rules(password)
    if problem:
        raise ValueError(problem)
    user.password_hash = hash_password(password)
    db.query(LoginSession).filter_by(user_id=user.id).delete()
    db.flush()
    audit.record(db, user.username, "updated", "user", user.id, f"Password reset for {user.username} from the command line")
    db.commit()
    return user


def main():
    print(f"Database: {settings.database_url}")
    db = SessionLocal()
    try:
        user = db.query(User).order_by(User.id).first()
        if not user:
            print("There is no account yet. Start CODesk and create one on the first page.")
            return 1
        print(f"Your username is: {user.username}")
        print("Type a new password. Nothing shows on screen while you type, that is normal.")
        print("At least 10 characters, with one capital letter and one number.")
        first = getpass.getpass("New password: ")
        second = getpass.getpass("Type it again: ")
        if first != second:
            print("The two passwords are not the same. Nothing was changed. Run the command again.")
            return 1
        try:
            reset(db, first)
        except ValueError as e:
            print(f"{e}. Nothing was changed. Run the command again.")
            return 1
        print(f"Done. Start the backend and log in as {user.username} with the new password.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
