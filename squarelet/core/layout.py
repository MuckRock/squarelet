"""Crispy form helpers"""

# Third Party
from crispy_forms.layout import Field as CrispyField


class Field(CrispyField):
    """Set common defaults"""

    def __init__(self, name, **kwargs):
        defaults = {
            "css_class": f"_cls-{name}Input",
            "wrapper_class": "_cls-field",
            "template": "account/field.html",
        }
        defaults.update(kwargs)
        super().__init__(name, **defaults)
