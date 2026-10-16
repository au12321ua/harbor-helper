"""One password hashing policy for invited users and token issuance."""
from argon2 import PasswordHasher

PASSWORDS = PasswordHasher()
