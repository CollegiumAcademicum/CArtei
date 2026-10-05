"""Required first-use profile confirmation for room holders."""

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from app.forms import ProfileSetupForm
from app.models import Tenant


@login_required
@require_http_methods(["GET", "POST"])
def profile_setup(request):
    tenant = request.profile_setup_tenant
    if tenant is None or not request.profile_setup_required:
        return redirect("dashboard")

    if request.method == "POST":
        form = ProfileSetupForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
                tenant.email = form.cleaned_data["email"]
                tenant.phone = form.cleaned_data["phone"] or None
                tenant.no_phone_number = form.cleaned_data["no_phone_number"]
                tenant.mailbox_list_opt_in = form.cleaned_data["mailbox_list_opt_in"] == "yes"
                tenant.profile_setup_completed_at = timezone.now()
                tenant.save(update_fields=[
                    "email", "phone", "no_phone_number", "mailbox_list_opt_in",
                    "profile_setup_completed_at",
                ])
            destination = request.POST.get("next", "")
            if destination.startswith("/") and url_has_allowed_host_and_scheme(
                destination, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
            ):
                return redirect(destination)
            return redirect("dashboard")
        next_path = request.POST.get("next", "")
    else:
        form = ProfileSetupForm(initial={
            "email": tenant.email,
            "phone": tenant.phone,
            "no_phone_number": tenant.no_phone_number,
        })
        next_path = request.GET.get("next", "")

    return render(request, "app/profile_setup.html", {
        "form": form,
        "next_path": next_path,
    })
