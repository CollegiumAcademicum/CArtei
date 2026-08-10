from django import forms

from app.models import Tenant
from app.tenant_access import EDITABLE_COLUMNS


class TenantForm(forms.ModelForm):
    # Model column is a plain CharField; declare EmailField so format is validated.
    email = forms.EmailField(required=True)

    class Meta:
        model = Tenant
        fields = EDITABLE_COLUMNS

    def __init__(self, *args, allowed_fields=None, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = set(allowed_fields or [])
        for name in list(self.fields):
            if name not in allowed:
                del self.fields[name]
