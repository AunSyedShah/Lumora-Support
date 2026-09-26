"""
Prompt template storage and rendering (SRS Steps 48-49).

Source of truth: prompt_templates/<name>/v<version>.txt (versioned in git), loaded into the
PromptTemplate table by `manage.py load_prompts`. A template file has these sections:

    ### DESCRIPTION   one line about this version
    ### SYSTEM        the system message
    ### USER          the user message with ${placeholders}
    ### RETRY         message sent after an invalid answer (uses ${errors})

The USER and RETRY parts are stored together in PromptTemplate.user_prompt, separated by the
RETRY marker, so each version is one self-contained unit.
"""

import re
from string import Template

from django.conf import settings

from .models import PromptTemplate

PROMPT_DIR = settings.BASE_DIR / "prompt_templates"
DEFAULT_PROMPT = "complaint_analysis"
RETRY_MARKER = "### RETRY"
SECTION = re.compile(r"^### (DESCRIPTION|SYSTEM|USER|RETRY)\s*$", re.MULTILINE)


class PromptError(Exception):
    pass


def parse_prompt_file(text):
    parts = SECTION.split(text)
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    missing = {"SYSTEM", "USER", "RETRY"} - set(sections)
    if missing:
        raise PromptError(f"Prompt file is missing section(s): {sorted(missing)}")
    return {
        "description": sections.get("DESCRIPTION", "")[:255],
        "system_prompt": sections["SYSTEM"],
        "user_prompt": f"{sections['USER']}\n\n{RETRY_MARKER}\n{sections['RETRY']}",
    }


def get_active_prompt(name=DEFAULT_PROMPT):
    prompt = PromptTemplate.objects.filter(name=name, is_active=True).first()
    if prompt is None:
        raise PromptError(f"No active prompt template named '{name}'. Run `manage.py load_prompts`.")
    return prompt


def render_messages(prompt, values):
    """Fill the placeholders. A missing value raises an error instead of sending a broken prompt."""
    user_part = prompt.user_prompt.split(RETRY_MARKER)[0].strip()
    try:
        user = Template(user_part).substitute(values)
    except KeyError as e:
        raise PromptError(f"Prompt {prompt.name} v{prompt.version} needs a value for {e}")
    return [{"role": "system", "content": prompt.system_prompt}, {"role": "user", "content": user}]


def render_retry(prompt, errors):
    retry_part = prompt.user_prompt.split(RETRY_MARKER)[1].strip()
    return Template(retry_part).safe_substitute(errors="\n".join(f"- {e}" for e in errors))


def activate(prompt):
    PromptTemplate.objects.filter(name=prompt.name).exclude(pk=prompt.pk).update(is_active=False)
    if not prompt.is_active:
        prompt.is_active = True
        prompt.save(update_fields=["is_active"])
