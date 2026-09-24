#!/usr/bin/python3

"""This creates the briefkastenliste

Written by Jakob M. Krieger, 30.04.2024
Mattermost: @jakob
"""

# imports

from collections import Counter
from pathlib import Path
import argparse
import pandas as pd
from pylatex import Document, Command, LongTable, MultiColumn, MultiRow, LargeText, Package, Command
from pylatex.utils import bold, italic, NoEscape, dumps_list, verbatim
from matplotlib import colormaps
from matplotlib.colors import to_hex

import subprocess

# argument parser

parser = argparse.ArgumentParser(prog="CreateBriefkastenliste")
parser.add_argument("residents_csv_fp", help="this should include all residents. Columns: forename, surename, flat_number")
parser.add_argument("--id", dest="id", default="id", help="column name for id")
parser.add_argument("--forename", dest="forename", default="forename", help="column name for forenames")
parser.add_argument("--surename", dest="surename", default="surename", help="column name for surenames")
parser.add_argument("--flatnumber", dest="flatnumber", default="flatnumber", help="column name for flat numbers")
parser.add_argument("--sort_by", dest="sort_by", default="surename", help="sort by this column name")
parser.add_argument("--pd_read_csv_kwargs", default="dict()", dest="pd_read_csv_kwargs", help="format as e.g. dict(skiprows=1, engine=\"python\")")
parser.add_argument("--mask_csv", default="mask.csv")
parser.add_argument("--mask_val", default="mask", help="column name for boolean mask")
parser.add_argument("--mask_id", default="id", help="id col on which is will be merged with the residents csv")
parser.add_argument("-o", default="briefkastenliste", dest="pdf_output_fp", help="output filepath of pdf file (without .pdf suffix)")

# helpers

def str_after_first_capitalized_char(x):
	return x[x.index([c for c in x if c.isupper()][0]):]

# latex

def build_briefkastenliste(df_residents, sort_by, surename_col, forename_col, flatnumber_col):
	df_residents[flatnumber_col] = df_residents[flatnumber_col].apply(lambda x: ".".join(x.split(".")[:2]))

	df_residents["sorting_letters"] = df_residents[sort_by].apply(lambda x: str_after_first_capitalized_char(x)[0]) # removes "von", "de", "van" or something like that
	df_residents["general_sorting"] = df_residents[sort_by].apply(lambda x: str_after_first_capitalized_char(x)) # removes "von", "de", "van" or something like that
	df_residents.sort_values(by="general_sorting", inplace=True)
	print("=== Sorting letters ===\n", df_residents.sorting_letters.value_counts())

	doc = Document(default_filepath="briefkastenliste", geometry_options={"paperwidth": "9.9cm", "paperheight": "21cm", "inner": ".5cm", "outer": ".5cm", "top": ".5cm", "bottom": "2cm"}, document_options=["12pt", "twoside", "openleft"])
	doc.preamble.append(Package("biolinum", options=["sfdefault"]))
	doc.preamble.append(Package("xcolor", options=["table"]))

	# long table cols: # first surname letter, name, flat number
	with doc.create(LongTable("||r|ll||", booktabs=False, row_height=1.3)) as table:
		# header
		table.add_hline()
		table.add_row([bold("Sortierung"), bold("Name"), bold("WG")])
		table.add_hline()
		table.end_table_header()
		# footer
		table.add_row([MultiColumn(3, align="r", data=italic("Fortführung auf nächster Seite..."))])
		table.end_table_footer()
		# last footer
		table.add_row([MultiColumn(3, align="r", data=italic("Auflistung fertig."))])
		table.add_hline()
		table.add_hline()
		table.end_table_last_footer()
		# data
		letter_specs = []
		N_letters = len(df_residents.sorting_letters.value_counts())
		for i_letter, (letter, n) in enumerate(df_residents.sorting_letters.value_counts().sort_index().items()):
			# n: number of residents with this letter as first letter in surname
			letter_specs.extend([(letter, n)] + [(letter, 0)]*(n-1))
			col_def = ", ".join([str(round(el, 2)) for el in colormaps["rainbow"](i_letter/max(N_letters-1, 1))[:3]])
			doc.preamble.append(Command("definecolor", [f"rainbow{letter}", "rgb", col_def]))


		for letter_spec, (_, row) in zip(letter_specs, df_residents.iterrows()):
			if letter_spec[1] != 0:
				table.add_hline()
				table.add_row([
					dumps_list([
						Command("cellcolor", f"rainbow{letter_spec[0]}!50"),
						Command("parbox", ["16pt", dumps_list([Command("centering"), LargeText(letter_spec[0])])], ["c"])
					]),
					f"{row.get(forename_col)[0]}. {row.get(surename_col)}",
					row.get(flatnumber_col)])
			else:
				table.add_row([Command("cellcolor", f"rainbow{letter_spec[0]}!50"), dumps_list([Command("parbox", ["16pt", f"{row.get(forename_col)[0]}."], "t"), row.get(surename_col).strip()]), row.get(flatnumber_col)])

		table.add_hline()


	doc.append("Letzte Aktualisierung: " + pd.Timestamp.now().strftime("%d.%m.%Y"))

	return doc


# main loop

if __name__ == "__main__":
	args = parser.parse_args()

	# load the residents csv
	df_residents = pd.read_csv(args.residents_csv_fp, **eval(args.pd_read_csv_kwargs))
	df_residents = df_residents.loc[:, [args.id, args.forename, args.surename, args.flatnumber]].dropna() # people who have no intranet id will be discarded!

	# load mask csv
	df_mask = pd.read_csv(args.mask_csv)
	df_mask = df_mask.loc[:, [args.mask_id, args.mask_val]].dropna()

	# lower case all id names
	df_residents[args.id] = df_residents[args.id].str.lower().str.strip()
	df_mask[args.mask_id] = df_mask[args.mask_id].str.lower().str.strip()

	# remove duplicates
	df_mask = df_mask.groupby(args.mask_id).last().reset_index()

	# mask the residents
	df_residents_inner = pd.merge(left=df_residents, right=df_mask, left_on=args.id, right_on=args.mask_id, how="inner").copy() # inner join because default is not on list and in user preferences also non-residents are listed
	df_residents_masked = df_residents_inner[df_residents_inner[args.mask_val] == True].copy()
	df_residents_left = pd.merge(left=df_residents, right=df_mask, left_on=args.id, right_on=args.mask_id, how="left").copy()
	df_residents_no_pref = df_residents_left[pd.isna(df_residents_left.username)]

	print("=== Preview of masked df_residents_masked ===\n", df_residents_masked)

	doc = build_briefkastenliste(
		df_residents_masked,
		sort_by=args.sort_by,
		surename_col=args.surename,
		forename_col=args.forename,
		flatnumber_col=args.flatnumber
	)

	print("=== These people didn't have a preference set ===")
	print(df_residents_no_pref.reset_index())

	print("=== These people don't want to be listed ===")
	print(df_residents_inner[df_residents_inner[args.mask_val] == False].reset_index())

	fp_without_sufix = Path(args.pdf_output_fp).parent / Path(args.pdf_output_fp).stem
	doc.generate_pdf(filepath=fp_without_sufix, clean_tex=True, compiler_args=["-f"])
	subprocess.run(["pdfjam", "--landscape", "--nup", "3x1", args.pdf_output_fp, "--outfile", str(fp_without_sufix) + "-pdfjam.pdf"], shell=False, check=True)
