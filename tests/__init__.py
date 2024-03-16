import unittest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy_signing import Signatures, RateLimitExceeded, KeyDoesNotExist, KeyExpired, ScopeMismatch, AlreadyRotated

class TestSignatures(unittest.TestCase):
    def setUp(self):
        # Connect to an in-memory database for tests.
        self.engine = create_engine('sqlite:///:memory:')
        self.Session = scoped_session(sessionmaker(bind=self.engine))
        # Create a new instance of Signatures for each test.
        self.signatures = Signatures(db_uri='sqlite:///:memory:', rate_limiting=True, rate_limiting_max_requests=2, rate_limiting_period=timedelta(seconds=10))

    def tearDown(self):
        # Drop all tables and close the session after each test.
        self.signatures.Base.metadata.drop_all(self.engine)
        self.Session.remove()

    def test_key_generation_and_storage(self):
        """Test that a key can be generated, stored, and retrieved."""
        key = self.signatures.write_key(scope='test', active=True)
        self.assertIsNotNone(key)
        stored_key = self.signatures.get_key(key)
        self.assertEqual(stored_key['signature'], key)

    def test_expire_key(self):
        """Test expiring a key."""
        key = self.signatures.write_key(scope='test', active=True)
        self.assertTrue(self.signatures.expire_key(key))
        with self.assertRaises(KeyExpired):
            self.signatures.verify_key(signature=key, scope='test')

    def test_rotate_key(self):
        """Test key rotation."""
        old_key = self.signatures.write_key(scope=['test'], active=True)
        new_key = self.signatures.rotate_key(key=old_key)
        self.assertNotEqual(old_key, new_key)
        with self.assertRaises(KeyExpired):
            self.signatures.verify_key(signature=old_key, scope=['test'])
        self.assertTrue(self.signatures.verify_key(signature=new_key, scope=['test']))

    def test_rate_limiting(self):
        """Test rate limiting."""
        key = self.signatures.write_key(scope='test', active=True)
        self.signatures.verify_key(signature=key, scope='test')  # First request should pass.
        self.signatures.verify_key(signature=key, scope='test')  # Second request should pass.
        with self.assertRaises(RateLimitExceeded):
            self.signatures.verify_key(signature=key, scope='test')  # Third request should fail.

    def test_key_scope_mismatch(self):
        """Test verifying a key with a mismatched scope."""
        key = self.signatures.write_key(scope='test1', active=True)
        with self.assertRaises(ScopeMismatch):
            self.signatures.verify_key(signature=key, scope='test2')

    def test_verify_nonexistent_key(self):
        """Test verifying a non-existent key."""
        with self.assertRaises(KeyDoesNotExist):
            self.signatures.verify_key(signature='nonexistent_key', scope='test')

    def test_rotation_of_already_rotated_key(self):
        """Test rotation of an already rotated key."""
        key = self.signatures.write_key(scope='test', active=True)
        new_key = self.signatures.rotate_key(key=key)
        with self.assertRaises(AlreadyRotated):
            self.signatures.rotate_key(key=key)

    def test_rotation_of_inactive_key(self):
        """Test attempting to rotate an inactive key."""
        key = self.signatures.write_key(scope='test', active=True)
        self.signatures.expire_key(key)
        with self.assertRaises(KeyExpired):
            self.signatures.rotate_key(key=key)

if __name__ == '__main__':
    unittest.main()
