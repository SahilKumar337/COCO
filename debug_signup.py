import database
try:
    user_id = database.create_user(
        email="test@example.com",
        name="Test",
        password_hash="fakehash",
        is_admin=True
    )
    print("Success:", user_id)
except Exception as e:
    import traceback
    traceback.print_exc()
