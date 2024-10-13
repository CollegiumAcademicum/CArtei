from django.shortcuts import get_object_or_404, redirect, render

from .forms import EntryForm
from .models import Entry
import csv


# List entries
def entry_list(request):
    search_query = request.GET.get("search", "")
    if search_query:
        entries = Entry.objects.filter(name__icontains=search_query)
    else:
        entries = Entry.objects.all()
    return render(request, "entry_list.html", {"entries": entries})


# Create entry
def entry_create(request):
    if request.method == "POST":
        form = EntryForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect("entry_list")
    else:
        form = EntryForm()
    return render(request, "entry_form.html", {"form": form})


# Update entry
def entry_update(request, pk):
    entry = get_object_or_404(Entry, pk=pk)
    if request.method == "POST":
        form = EntryForm(request.POST, request.FILES, instance=entry)
        if form.is_valid():
            form.save()
            return redirect("entry_list")
    else:
        form = EntryForm(instance=entry)
    return render(request, "entry_form.html", {"form": form})


# Delete entry
def entry_delete(request, pk):
    entry = get_object_or_404(Entry, pk=pk)
    if request.method == "POST":
        entry.delete()
        return redirect("entry_list")
    return render(request, "entry_confirm_delete.html", {"entry": entry})


# Populate entries from CSV
def populate_from_csv(request):
    if request.method == "POST" and request.FILES["csv_file"]:
        csv_file = request.FILES["csv_file"]
        decoded_file = csv_file.read().decode("utf-8").splitlines()
        reader = csv.DictReader(decoded_file)
        for row in reader:
            Entry.objects.create(
                name=row["Name"],
                pronouns=row["Pronomen"],
                birthday=row["Geburtsdatum"],
                phone_number=row["Telefonnummer"],
                email=row["E-Mail"],
                study=row["Studiengang/Ausbildung"],
                institution=row["Hochschule/Ausbildungsstätte"],
            )
        return redirect("entry_list")
    return render(request, "populate_from_csv.html")
