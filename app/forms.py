from datetime import date

from django import forms
from django.db.models import Q

from app.models import Room, Tenant, TenantRoomAssignment
from app.tenant_access import EDITABLE_COLUMNS


class TenantForm(forms.ModelForm):
    # Model column is a plain CharField; declare EmailField so format is validated.
    email = forms.EmailField(required=True)

    class Meta:
        model = Tenant
        fields = EDITABLE_COLUMNS

    def __init__(self, *args, allowed_fields=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Native browser date picker (like the engagement surveys): <input type="date">.
        # Force ISO so existing values prefill and submissions parse under the de-de locale.
        for field in self.fields.values():
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(
                    attrs={"type": "date", "class": "ca-input"}, format="%Y-%m-%d"
                )
                field.input_formats = ["%Y-%m-%d"]
        allowed = set(allowed_fields or [])
        for name in list(self.fields):
            if name not in allowed:
                del self.fields[name]


class TenantRoomAssignmentForm(forms.ModelForm):
    class Meta:
        model = TenantRoomAssignment
        fields = [
            "room", "moved_in", "moved_out", "mailbox_key_received",
            "mailbox_key_returned", "is_sublet", "sublet_of_tenant",
            "key_received", "key_returned", "deposit_iban",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["room"].queryset = Room.objects.select_related("wg__building").order_by(
            "wg__building__name", "wg__name", "name"
        )
        self.fields["room"].label_from_instance = lambda r: f"{r.wg.building.name} · {r.wg.name} · {r.name}"
        self.fields["sublet_of_tenant"].queryset = Tenant.objects.order_by("last_name", "first_name")
        self.fields["sublet_of_tenant"].required = False
        for field in self.fields.values():
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(
                    attrs={"type": "date", "class": "ca-input"}, format="%Y-%m-%d"
                )
                field.input_formats = ["%Y-%m-%d"]
            elif hasattr(field, "widget") and not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "ca-input")
        # Cards render OUTSIDE <form id="form-housing"> (so the per-assignment
        # document <form>s aren't nested inside it), so associate every field
        # with the housing form via the HTML5 form attribute — the same trick
        # the Speichern button uses. Submission is byte-for-byte like nesting.
        for field in self.fields.values():
            field.widget.attrs["form"] = "form-housing"

    def clean(self):
        cleaned = super().clean()
        room, source = cleaned.get("room"), cleaned.get("sublet_of_tenant")
        # "Untervermietet von" must actually rent the selected room (active assignment).
        if room and source:
            today = date.today()
            rents = (
                TenantRoomAssignment.objects.filter(room=room, tenant=source)
                .filter(Q(moved_out__isnull=True) | Q(moved_out__gt=today))
                .exists()
            )
            if not rents:
                self.add_error(
                    "sublet_of_tenant",
                    "Diese Person mietet das ausgewählte Zimmer nicht.",
                )
        return cleaned
