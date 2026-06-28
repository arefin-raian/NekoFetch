from nekofetch.bots.admin.handlers.commands import _help_text, admin_commands
from nekofetch.domain.enums import Role
print("CMDS:", [(c.command, c.description) for c in admin_commands()])
print(_help_text(Role.ADMIN))
