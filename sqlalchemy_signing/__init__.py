from .__metadata__ import (__name__, __author__, __credits__, __version__, 
                       __license__, __maintainer__, __email__)
import datetime, secrets
from functools import wraps
from sqlalchemy import (
    func, 
    literal, 
    create_engine, 
    Column, 
    String, 
    Boolean, 
    DateTime, 
    Integer, 
    ForeignKey, 
    JSON,
)
from sqlalchemy.orm import (
    sessionmaker, 
    relationship, 
    scoped_session, 
    backref,
    declarative_base,
)
from sqlalchemy.exc import SQLAlchemyError
from typing import Union, List, Dict, Any, Optional



LocalBase = declarative_base()

def create_signing_class(Base=None, datetime_override=datetime.datetime.utcnow, email_foreign_key_mapping: None | str = None):
    """Factory for the Signing class, which allows several overrides for customization"""
    if Base is None:
        Base = LocalBase

    class Signing(Base):
        __tablename__ = 'signing'
        signature = Column(String(1000), primary_key=True)
        
        # Allow users to map email as a foreign key, see
        # https://github.com/signebedi/sqlalchemy_signing/issues/16
        if isinstance(email_foreign_key_mapping, str):
            email = Column(String(100), ForeignKey(email_foreign_key_mapping))
        else:
            email = Column(String(100)) 

        scope = Column(JSON())
        active = Column(Boolean)
        timestamp = Column(DateTime, nullable=False, default=datetime_override)
        expiration = Column(DateTime, nullable=False, default=datetime_override)
        # A 0 expiration int means it will never expire
        expiration_int = Column(Integer, nullable=False, default=0)
        request_count = Column(Integer, default=0)
        last_request_time = Column(DateTime, default=datetime_override)
        previous_key = Column(String(1000), ForeignKey('signing.signature'), nullable=True)
        rotated = Column(Boolean)
        # parent = db.relationship("Signing", remote_side=[signature]) # self referential relationship
        children = relationship('Signing', backref=backref('parent', remote_side=[signature])) # self referential relationship

    return Signing

Signing = create_signing_class()

class RateLimitExceeded(Exception):
    """
    An exception that is raised when the request count for a specific signature 
    exceeds the maximum allowed requests within a specified time period in the 
    Signatures class.

    This exception is used to signal that the rate limit has been exceeded, so the 
    calling code can catch this exception and handle it appropriately - for example,
    by sending an HTTP 429 Too Many Requests response to a client.
    """
    pass

class KeyDoesNotExist(Exception):
    """
    An exception that is raised when a requested signing key does not exist in the 
    system. This could happen if the key has been deleted, never created, or if there 
    is a mismatch in the key identifier used for lookup.

    This exception indicates that the operation cannot proceed without a valid signing 
    key, and the calling code should catch this exception to handle these cases 
    appropriately.
    """
    pass

class KeyExpired(Exception):
    """
    An exception that is raised when the signing key's expiration time has passed
    or the key is marked inactive. Expired keys are considered invalid for crypto
    graphic operations.

    This exception helps in enforcing security protocols where only active keys should 
    be used, allowing the calling code to handle such situations accordingly, such as 
    notifying the user or selecting an alternate key.
    """
    pass

class ScopeMismatch(Exception):
    """
    An exception that is raised when the scope associated with the signing key does not 
    match any of the required scopes specified in the operation.

    This exception is crucial for maintaining scope-based access control, ensuring that 
    operations are performed only with keys that have the appropriate scope. The calling 
    code should handle this exception to enforce correct scope usage.
    """
    pass

class AlreadyRotated(Exception):
    """
    An exception that is raised when there is an attempt to rotate an already-rotated
    key.

    This exception will help prevent keys that have gone stale from being rotated and 
    producing further children keys.
    """
    pass


class Signatures:
    """
    The Signatures class handles operations related to the creation, management, and validation 
    of signing keys in the database.
    """
    
    def __init__(
        self, 
        db_uri:str, 
        safe_mode:bool=True, 
        byte_len:int=24, 
        rate_limiting=False, 
        rate_limiting_max_requests=10, 
        rate_limiting_period=datetime.timedelta(minutes=1),
        datetime_override=datetime.datetime.utcnow,
        Base=LocalBase,
        Signing=Signing,
        create_tables=True, # If True, this will run create_all on the database tables
    ):
        """
        Initializes a new instance of the Signatures class.

        Args:
            db_uri (str): A database URI to add the signing table to.
            safe_mode (bool, optional): If safe_mode is enabled, we will prevent rotation of disabled or rotated keys. Defaults to True.
            byte_len (int, optional): The length of the generated signing keys. Defaults to 24.
            rate_limiting (bool, optional): If rate_limiting is enabled, we will impose key-by-key rate limits. Defaults to False.
            rate_limiting_max_requests (int, optional): Maximum allowed requests per time period.
            rate_limiting_period (datetime.timedelta, optional): Time period for rate limiting. Defaults to 1 hour.
        """

        # if not Base:
        #     self.Base = declarative_base()
        # else:
        #     self.Base = Base
        # self.Base = declarative_base()

        self.Signing = self.get_model()

        self.engine = create_engine(db_uri, echo=True)
        self.Session = scoped_session(sessionmaker(bind=self.engine))

        # Create the table for Signing, without affecting existing tables
        # self.Base.metadata.create_all(self.engine, tables=[self.Signing.__table__])
        if create_tables:
            Base.metadata.create_all(self.engine, tables=[self.Signing.__table__])


        self.byte_len = byte_len

        # Set safe mode to prevent disabled/rotated keys from being rotated
        self.safe_mode = safe_mode

        # Set rate limiting attributes
        self.rate_limiting = rate_limiting
        self.rate_limiting_max_requests = rate_limiting_max_requests
        self.rate_limiting_period = rate_limiting_period

        self.datetime_override = datetime_override

    class request_limiter:
        """
        A descriptor class that wraps a function with rate limiting logic. This descriptor is meant to 
        be used as a decorator for methods in the Signatures class.

        If rate limiting is enabled in the Signatures instance, this decorator checks the request count 
        for the provided signature and raises a `RateLimitExceeded` exception if the count exceeds 
        the max requests allowed in a set time period. 

        If the time period has passed since the last request, it resets the request count. If the request 
        count is within limits, it increments the request count and updates the time of the last request.

        If rate limiting is not enabled, the descriptor simply calls the original function.

        Args:
            func (Callable): The function to wrap with rate limiting logic.

        Returns:
            wrapper (Callable): The wrapped function which now includes rate limiting logic.
        """

        def __init__(self, func):
            self.func = func

        def __get__(self, instance, owner):
            @wraps(self.func)
            def wrapper(signature, *args, **kwargs):

                # If rate limiting has not been enabled, then we always return True
                if not instance.rate_limiting:
                    return self.func(instance, signature, *args, **kwargs)

                Signing = instance.get_model()

                with instance.Session() as session:
                    signing_key = session.query(Signing).filter_by(signature=signature).first()

                    # If the key does not exist
                    if signing_key:

                        # Reset request_count if period has passed since last_request_time
                        if instance.datetime_override() - signing_key.last_request_time >= instance.rate_limiting_period:
                            signing_key.request_count = 0
                            signing_key.last_request_time = instance.datetime_override()

                        # Check if request_count exceeds max_requests
                        if signing_key.request_count >= instance.rate_limiting_max_requests:
                            raise RateLimitExceeded("Too many requests. Please try again later.")

                        # If limit not exceeded, increment request_count and update last_request_time
                        signing_key.request_count += 1
                        signing_key.last_request_time = instance.datetime_override()

                        session.commit()

                return self.func(instance, signature, *args, **kwargs)
            return wrapper

    def generate_key(self, length:int=None) -> str:
        """
        Generates a signing key with the specified byte length. 
        Note: byte length generally translates to about 1.3 times as many chars,
        see https://docs.python.org/3/library/secrets.html.

        Args:
            length (int, optional): The length of the generated signing key. Defaults to None, in which case the byte_len is used.

        Returns:
            str: The generated signing key.
        """

        if not length: 
            length = self.byte_len
        return secrets.token_urlsafe(length)

    def write_key(self, scope:str|list|None=None, expiration:int=0, active:bool=True, email:str=None, previous_key:str=None) -> str:
        """
        Writes a newly generated signing key to the database.

        This function will continuously attempt to generate a key until a unique one is created. 

        Args:
            scope (str, list): The scope within which the signing key will be valid. Defaults to None.
            expiration (int, optional): The number of hours after which the signing key will expire. 
                If not provided or equals 0, the expiration will be set to zero (no-expiry). Defaults to 0.
            active (bool, optional): The status of the signing key. Defaults to True.
            email (str, optional): The email associated with the signing key. Defaults to None.
            previous_key (str, optional): The previous key to associate with this key, in the case of key rotation. Defaults to None.

        Returns:
            str: The generated and written signing key.
        """
        Signing = self.get_model()

        with self.Session() as session:
            # Generate a unique key
            key = self.generate_key()
            
            # Ensure the key is unique
            while session.query(Signing).filter_by(signature=key).first() is not None:
                key = self.generate_key()

            # This will ensure scope is always a list
            modified_scope: list = []

            if isinstance(scope, str):
                modified_scope = [scope.lower()]
            elif isinstance(scope, list):
                modified_scope = [x.lower() for x in scope]


            # Prepare the data for the new key
            signing_fields = {
                'signature': key, 
                'scope': modified_scope,
                'email': email.lower() if email else "", 
                'active': active,
                'rotated': False,
                'expiration': (self.datetime_override() + datetime.timedelta(hours=expiration)) if expiration else datetime.datetime(9999, 12, 31, 23, 59, 59),
                'expiration_int': expiration,
                'timestamp': self.datetime_override(),
            }

            if previous_key:
                signing_fields['previous_key'] = previous_key

            new_key = Signing(**signing_fields)
            
            session.add(new_key)
            session.commit()


        return key

    def expire_key(self, key):
        """
        Expires a signing key in the database.

        This function finds the key in the database and disables it by setting its 'active' status to False.
        If the key does not exist, it raises an exception.

        Args:
            key (str): The signing key to be expired.

        Returns:
            bool: True indicating the success of the operation.
        """

        Signing = self.get_model()

        # Start a session
        session = self.Session()

        signing_key = session.query(Signing).filter_by(signature=key).first()
        if not signing_key:
            session.close()  # Ensure to close the session in case of early exit
            raise KeyDoesNotExist("This key does not exist.")

        # This will disable the key
        signing_key.active = False

        # Commit the change to the database
        session.commit()

        # Close the session
        session.close()

        return True
    

    @request_limiter
    def verify_key(self, signature, scope):
        """
        Validates a request by verifying the given signing key against a specific scope.
        
        This function wraps the `check_key` function and adds rate limiting support. 
        If rate limiting is enabled, it checks whether the request count for the signature 
        has exceeded the maximum allowed requests within the specified time period.
        
        If the rate limit is exceeded, it raises a `RateLimitExceeded` exception and returns False.
        If the rate limit is not exceeded, or is not enabled, this calls the `check_key` function 
        to verify the key.
        
        Args:
            signature (str): The signing key to be verified.
            scope (str): The scope against which the signing key will be validated.

        Returns:
            bool: True if the signing key is valid and hasn't exceeded rate limit, False otherwise.

        Raises:
            RateLimitExceeded: If the number of requests with this signing key exceeds 
            the maximum allowed within the specified time period.
        """

        # try:
        #     valid = self.check_key(signature, scope)
        # except RateLimitExceeded as e:
        #     print(e)  # Or handle the exception in some other way
        #     return False
        # return valid

        return self.check_key(signature, scope)

    def check_key(self, signature, scope):
        """
        Checks the validity of a given signing key against a specific scope.

        This function checks if the signing key exists, if it is active, if it has not expired,
        and if its scope matches the provided scope. If all these conditions are met, the function
        returns True, otherwise, it returns False.

        Args:
            signature (str): The signing key to be verified.
            scope (str): The scope against which the signing key will be validated.

        Returns:
            bool: True if the signing key is valid and False otherwise.
        """

        Signing = self.get_model()

        with self.Session() as session:
            signing_key = session.query(Signing).filter_by(signature=signature).first()

        # if the key doesn't exist
        if not signing_key:
            # return False
            raise KeyDoesNotExist("This key does not exist.")

        # if the signing key is set to inactive
        if not signing_key.active:
            # return False
            raise KeyExpired("This key is no longer active.")

        # if the signing key's expiration time has passed
        if signing_key.expiration < self.datetime_override():
            self.expire_key(signature)
            # return False
            raise KeyExpired("This key is expired.")

        # Convert scope to a list if it's a string
        if isinstance(scope, str):
            scope = [scope]

        # if the signing key's scope doesn't match any of the required scopes
        if signing_key.scope and not set(scope).intersection(set(signing_key.scope)):
            raise ScopeMismatch("This key does not match the required scope.")

        # # if the signing key's scope doesn't match the required scope
        # if signing_key.scope != scope:
        #     return False

        return True

    def get_model(self):

        """
        Return a single instance of the Signing class, which represents the Signing table in the database.

        Attributes:
            signature (str): The primary key of the Signing table. This field is unique for each entry.
            email (str): The email associated with a specific signing key.
            scope (str): The scope within which the key is valid.
            active (bool): The status of the signing key. If True, the key is active.
            timestamp (datetime): The date and time when the signing key was created.
            expiration (datetime): The date and time when the signing key is set to expire.
        """

        if not hasattr(self, '_model'):
            self._model = Signing

        return self._model


    def query_keys(self, active:bool=None, scope:str=None, email:str=None, previous_key:str=None) -> Union[List[Dict[str, Any]], bool]:
        """
        Query signing keys by active status, scope, email, and previous_key.

        This function returns a list of signing keys that match the provided parameters.
        If no keys are found, it returns False.

        Args:
            active (bool, optional): The active status of the signing keys. Defaults to None.
            scope (str, optional): The scope of the signing keys. Defaults to None.
            email (str, optional): The email associated with the signing keys. Defaults to None.
            previous_key (str, optional): The previous_key associated with the signing keys. Defaults to None.

        Returns:
            Union[List[Dict[str, Any]], bool]: A list of dictionaries where each dictionary contains the details of a signing key,
            or False if no keys are found.
        """

        Signing = self.get_model()

        with self.Session() as session:
            query = session.query(Signing)

            if active is not None:
                query = query.filter(Signing.active == active)

            # Convert scope to a list if it's a string
            if isinstance(scope, str):
                scope = [scope]

            if scope:

                for s in scope:
                    # https://stackoverflow.com/a/44250678/13301284
                    query = query.filter(Signing.scope.comparator.contains(s))
                    
            if email:
                query = query.filter(Signing.email == email)

            if previous_key:
                query = query.filter(Signing.previous_key == previous_key)

            result = query.all()

        if not result:
            raise Exception("No results found for given parameters.")

        return [{'signature': key.signature, 'email': key.email, 'scope': key.scope, 'active': key.active, 'timestamp': key.timestamp, 'expiration': key.expiration, 'previous_key': key.previous_key, 'rotated': key.rotated} for key in result]

    def get_all(self) -> List[Dict[str, Any]]:

        """
        Query all values in the Signing table.
        If no keys are found, it returns an empty list.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries where each dictionary contains the details of a signing key.

        """
        return [{'signature': key.signature, 'email': key.email, 'scope': key.scope, 'active': key.active, 'timestamp': key.timestamp, 'expiration': key.expiration, 'previous_key': key.previous_key, 'rotated': key.rotated} for key in self.get_model().query.all()]


    def get_key(self, signature:str) -> Dict[str, Any]:

        """
        Query for a single key in the Signing table.
        If no keys are found, it returns an empty dict.

        Args:
            signature (str): The signature you'd like to get.

        Returns:
            Dict[str, Any]: A dictionary containining the details of a signing key, if found.

        """

        Signing = self.get_model()

        with self.Session() as session:
            key = session.query(Signing).filter_by(signature=signature).first()

        if key:
            return {'signature': key.signature, 'email': key.email, 'scope': key.scope, 'active': key.active, 'timestamp': key.timestamp, 'expiration': key.expiration, 'previous_key': key.previous_key, 'rotated': key.rotated}

        return {}




    def rotate_keys(self, time_until:int=1, scope=None, only_active_key_rotation:bool=True, overwrite_scope:list|str|None=None) -> bool:
        """
        Rotates all keys that are about to expire.
        This is written with the background processes in mind. This can be wrapped in a celerybeat schedule or celery task.
        Args:
            time_until (int): rotate keys that are set to expire in this many hours.
            scope (str, list): rotate keys with this scope. If None, all scopes are considered.
            only_active_key_rotation (book): if true, this will only enable the system to rotate keys that are active.
            overwrite_scope (str, list): If set, this will set a new scope for the new key. Defaults to None.
        Returns:
            List[Tuple[str, str]]: A list of tuples containing old keys and the new keys replacing them
        """


        Signing = self.get_model()

        # get keys that will expire in the next time_until hours
        with self.Session() as session:
            query = session.query(Signing.signature).filter(  # Query ONLY the signature column
                Signing.expiration <= (self.datetime_override() + datetime.timedelta(hours=time_until)),
                Signing.active == only_active_key_rotation
            )

            # Convert scope to a list if it's a string
            if isinstance(scope, str):
                scope = [scope]

            if scope:
                for s in scope:
                    # https://stackoverflow.com/a/44250678/13301284
                    query = query.filter(Signing.scope.comparator.contains(s))

            # Get list of signature strings (not objects)
            expiring_signatures = [row[0] for row in query.all()]  # Extract signature from each row tuple

            key_list = []

            for signature in expiring_signatures:
                # signature is now just a string, no object to get detached
                old_key = signature
                new_key = self.rotate_key(signature, overwrite_scope=overwrite_scope)
                key_list.append((old_key, new_key))


        # We may need to potentially modify the return behavior to provide greater detail ... 
        # for example, a list of old keys mapped to their new keys and emails.
        # return True
        return key_list

    def rotate_key(self, key: str, expiration:Optional[int]=None, overwrite_scope:list|str|None=None) -> str:
        """
        Replaces an active key with a new key with the same properties, and sets the old key as inactive.
        Args:
            key (str): The signing key to be rotated.
            expiration (int): The number of hours until the new key will expire.
            overwrite_scope (str, list): If set, this will set a new scope for the new key. Defaults to None.

        Returns:
            str: The new signing key.
        """

        session = self.Session()

        try:
            Signing = self.get_model()

            signing_key = session.query(Signing).filter_by(signature=key).first()

            if not signing_key:
                raise KeyDoesNotExist("This key does not exist.")

            if self.safe_mode and signing_key.rotated:
                raise AlreadyRotated("Key has already been rotated")

            if self.safe_mode and not signing_key.active:
                raise KeyExpired("You cannot rotate a disabled key")

            # Disable old key
            signing_key.active = False
            signing_key.rotated = True

            # If no expiration int is passed, we inherit the parent's
            if expiration is None:
                expiration = signing_key.expiration_int

            # Set a new variable that will contain the scope that will be written to this new key
            modified_scope: list

            if isinstance(overwrite_scope, str):
                modified_scope = [overwrite_scope.lower()]
            elif isinstance(overwrite_scope, list):
                modified_scope = [x.lower() for x in overwrite_scope]
            else:
                modified_scope=signing_key.scope


            # Generate a new key with the same properties
            new_key = self.write_key(
                scope=modified_scope,
                expiration=expiration,
                active=True, 
                email=signing_key.email,
                previous_key=signing_key.signature,  # Assign old key's signature to the previous_key field of new key
            )
            
        except Exception as e:
            session.rollback()  # Rollback in case of any exception
            raise e
        else:
            session.commit()  # Commit if everything is fine
        finally:
            session.close()  # Ensure the session is closed in any case

        return new_key