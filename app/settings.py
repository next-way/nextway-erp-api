import os
from pathlib import Path

from dotenv import dotenv_values

SETTINGS = {
    **dotenv_values(
        (Path().parent / ".env.shared")
    ),  # load shared development variables
    **dotenv_values((Path().parent / ".env.secret")),  # load sensitive variables
    **os.environ,  # override loaded values with environment variables
}
