"""
Integration tests for the customer notification bell
(routes/booking.py: /notifications, /notifications/read-all).
"""

from extensions import db
from models import Notification
from tests.conftest import login


class TestNotifications:
    def test_requires_login(self, client):
        resp = client.get("/notifications")
        assert resp.status_code in (302, 308)

    def test_shows_own_notification(self, client, customer_user):
        db.session.add(Notification(user_id=customer_user.id, kind="promo",
                                    title="A little something for you",
                                    body="10% off your next set."))
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        resp = client.get("/notifications")
        assert b"A little something for you" in resp.data

    def test_does_not_show_another_users_notification(self, client, customer_user):
        from models import User
        other = User(full_name="Other Person", email="other@example.com")
        other.set_password("Password@123")
        db.session.add(other)
        db.session.commit()

        db.session.add(Notification(user_id=other.id, kind="promo",
                                    title="Not yours to see",
                                    body="Should stay private."))
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        resp = client.get("/notifications")
        assert b"Not yours to see" not in resp.data

    def test_opening_the_page_marks_unread_as_read(self, client, customer_user):
        note = Notification(user_id=customer_user.id, kind="promo",
                            title="Unread notice", body="Read me.",
                            is_read=False)
        db.session.add(note)
        db.session.commit()
        note_id = note.id

        login(client, customer_user.email, "Password@123")
        client.get("/notifications")

        db.session.refresh(note)
        assert Notification.query.get(note_id).is_read is True

    def test_read_all_marks_everything_read(self, client, customer_user):
        for i in range(3):
            db.session.add(Notification(user_id=customer_user.id, kind="promo",
                                        title=f"Notice {i}", body="Body",
                                        is_read=False))
        db.session.commit()

        login(client, customer_user.email, "Password@123")
        client.post("/notifications/read-all", follow_redirects=True)

        unread = Notification.query.filter_by(user_id=customer_user.id,
                                               is_read=False).count()
        assert unread == 0
