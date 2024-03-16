import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
from sqlalchemy_signing import Signatures, RateLimitExceeded, KeyDoesNotExist, KeyExpired, ScopeMismatch, AlreadyRotated

class TestSignatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Setup that is run once for all tests
        cls.db_uri = "sqlite:///:memory:"
        cls.signatures = Signatures(db_uri=cls.db_uri)

    def test_initialization(self):
        self.assertEqual(self.signatures.byte_len, 24)
        self.assertTrue(self.signatures.safe_mode)
        self.assertFalse(self.signatures.rate_limiting)
    
    def test_generate_key(self):
        key = self.signatures.generate_key()
        self.assertIsInstance(key, str)
        self.assertEqual(len(key), 32)  # Default byte_len=24 results in a 32 character string
    
    def test_write_and_query_key(self):
        key = self.signatures.write_key(scope="test", active=True)
        self.assertIsInstance(key, str)
        queried_keys = self.signatures.query_keys(active=True, scope="test")
        self.assertIsInstance(queried_keys, list)
        self.assertEqual(queried_keys[0]['signature'], key)
    
    @patch.object(Signatures, 'rate_limiting', True)
    def test_rate_limiting(self):
        with self.assertRaises(RateLimitExceeded):
            for _ in range(11):  # Assuming default rate_limiting_max_requests is 10
                self.signatures.verify_key("some_signature", "some_scope")
    
    def test_expire_key(self):
        key = self.signatures.write_key(active=True)
        self.assertTrue(self.signatures.expire_key(key))
        with self.assertRaises(KeyDoesNotExist):
            self.signatures.expire_key("non_existing_key")
    
    def test_verify_key(self):
        key = self.signatures.write_key(scope="test", active=True)
        self.assertTrue(self.signatures.verify_key(key, "test"))
        with self.assertRaises(ScopeMismatch):
            self.signatures.verify_key(key, "invalid_scope")
        with self.assertRaises(KeyDoesNotExist):
            self.signatures.verify_key("non_existing_key", "test")
    
    def test_rotate_keys(self):
        key = self.signatures.write_key(scope="rotation_test", expiration=1)
        rotated_keys = self.signatures.rotate_keys(time_until=2, scope="rotation_test")
        self.assertIsInstance(rotated_keys, list)
        self.assertNotEqual(rotated_keys[0][0], rotated_keys[0][1])  # Old key should not equal new key
    
    def test_exceptions(self):
        with self.assertRaises(KeyExpired):
            self.signatures.rotate_key("non_active_key")
        with self.assertRaises(AlreadyRotated):
            key = self.signatures.write_key(scope="exception_test", active=True)
            self.signatures.rotate_key(key)
            self.signatures.rotate_key(key)  # Attempting to rotate the same key again

if __name__ == '__main__':
    unittest.main()
