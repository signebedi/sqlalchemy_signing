![Signing logo](https://raw.githubusercontent.com/signebedi/sqlalchemy_signing/master/docs/combined.png)

## sqlalchemy_signing

[![License: BSD-3-Clause](https://img.shields.io/github/license/signebedi/sqlalchemy_signing?color=dark-green)](https://github.com/signebedi/sqlalchemy_signing/blob/master/LICENSE) 
<!-- [![PyPI version](https://badge.fury.io/py/sqlalchemy_signing.svg)](https://pypi.org/project/sqlalchemy_signing/)
[![Downloads](https://static.pepy.tech/personalized-badge/sqlalchemy_signing?period=total&units=international_system&left_color=grey&right_color=brightgreen&left_text=Downloads)](https://pepy.tech/project/sqlalchemy_signing)
[![sqlalchemy_signing tests](https://github.com/signebedi/sqlalchemy_signing/workflows/tests/badge.svg)](https://github.com/signebedi/sqlalchemy_signing/actions) -->
[![Buy me a coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee--brightgreen.svg?logo=buy-me-a-coffee&logoColor=brightgreen)](https://www.buymeacoffee.com/signebedi)

a signing key extension for sqlalchemy


### About

The sqlalchemy_signing library is a useful tool for Python applications using sqlalchemy that require secure and robust management of signing keys. It grew out of the [Flask-Signing](https://github.com/signebedi/Flask-Signing) project, which was more tightly coupled to the Flask framework. Do you need to generate single-use tokens for one-time actions like email verification or password reset? sqlalchemy_signing can handle that. Are you looking for a simple method for managing API keys? Look no further. 

### Installation

First, install the sqlalchemy_signing package. You can do this with pip:

```bash
pip install sqlalchemy_signing
```

### Basic Usage

After you've installed the sqlalchemy_signing package, you can use it in your Flask application. Here's an example of how you might do this:

```python
from sqlalchemy_signing import (
    Signatures,
    RateLimitExceeded
)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'  # Use your actual database URI
app.secret_key = "Your_Key_Here"

with app.app_context():
    signatures = Signatures(app.config['SQLALCHEMY_DATABASE_URI'], byte_len=24)


@app.route('/sign')
def sign():
    key = signatures.write_key(scope='test', expiration=1, active=True, email='test@example.com')
    return f'Key generated: {key}'

@app.route('/verify/<key>')
def verify(key):
    try:
        valid = signatures.verify_key(signature=key, scope='test')
        return f'Key valid: {valid}'
    except RateLimitExceeded:
        return "Rate limit exceeded"

@app.route('/expire/<key>')
def expire(key):
    expired = signatures.expire_key(key)
    return f'Key expired: {expired}'
    
@app.route('/all')
def all():
    all = signatures.get_all()
    return f'Response: {all}'
```

In this basic example, a new signing key is generated and written to the database when you visit the `/sign` route, and the key is displayed on the page. Then, when you visit the `/verify/<key>` route (replace <key> with the actual key), the validity of the key is checked and displayed. You can expire a key using the `/expire/<key>` route, and view all records with the `/all` route.

This is a rather basic example and your actual use of the sqlalchemy_signing package may be more complex depending on your needs. It's important to secure your signing keys and handle them appropriately according to your application's security requirements. Further usage examples can be found in the [examples](https://github.com/signebedi/sqlalchemy_signing/tree/master/examples) directory of the sqlalchemy_signing Github repository. 

### Developers

Contributions are welcome! You can read the developer docs at https://signebedi.github.io/sqlalchemy_signing. If you're interested, review (or add to) the feature ideas at https://github.com/signebedi/sqlalchemy_signing/issues.
