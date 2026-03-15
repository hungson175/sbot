"""Channel adapters — each platform is a channel.

Import all channel modules here so @register_channel decorators execute.
To add a new channel: create the module and import it below.
"""

from . import telegram  # noqa: F401
from . import messenger  # noqa: F401
# from . import slack      # noqa: F401  (future)
