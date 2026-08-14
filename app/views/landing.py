from django.shortcuts import render


def landing(request):
    """Public introduction / info page. No login required."""
    return render(request, "app/landing.html")