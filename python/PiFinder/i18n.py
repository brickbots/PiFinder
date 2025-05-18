import gettext

# Install the _("text") into global context for Internationalization
# On RasPi/Ubuntu the default locale is C.utf8, see `locale -a`, which locales are available
# You need to install `apt install language-pack_xx`, where xx is the ISO country code.
# Passing nothing as third parameter means the language is determined from environment variables (e.g. LANG)
gettext.install("PiFinder", "locale")
