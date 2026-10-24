from django.apps import AppConfig


class EmailAgentConfig(AppConfig):
    name = 'email_agent'

    def ready(self):
        from . import listener

        if listener.should_autostart():
            listener.start()
