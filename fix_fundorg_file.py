#!/usr/bin/env python3
import sys
import csv
from pathlib import Path


def read_mri_projects(mri_file):
    mri_projects = {}
    with open(mri_file, 'r') as f:
        mri_reader = csv.reader(f)
        for row in mri_reader:
            mri_projects[row[0].lower()] = row[1]
    return mri_projects


def read_startup_projects(startup_file):
    startup_projects = {}
    with open(startup_file, 'r') as f:
        startup_reader = csv.reader(f)
        for row in startup_reader:
            startup_projects[row[0].lower()] = row[1]
    return startup_projects


def main():
    debug_p = False
    rcm_dir = Path('/ifs/sysadmin/RCM')

    mri_file = rcm_dir / 'mri_projects.txt'
    startup_file = rcm_dir / 'startup_projects.txt'

    mri_projects = read_mri_projects(mri_file)
    startup_projects = read_startup_projects(startup_file)

    if debug_p:
        print(f'startup_projects = {startup_projects}')

    old_rows = []
    old_fundorg_file = 'fundorg_codes.csv'
    with open(old_fundorg_file, 'r') as csvfile:
        reader = csv.DictReader(csvfile)

        for row in reader:
            old_rows.append(row)

    # use latin_1 encoding because this will be used by Office of Research
    with open('fundorg_codes_fixed.csv', 'w', encoding='latin_1') as csvfile:
        fieldnames = ['Project', 'Fund-Org code', 'Class?', 'MRI?', 'Startup/Grant?', 'Share expiration', 'Last name', 'First name', 'Email']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in old_rows:
            row['Project'] = row['Project'].lower()
            row['Startup/Grant?'] = row['Project'] in startup_projects
            row['MRI?'] = row['Project'] in mri_projects

            if row['Startup/Grant?']:
                row['Share expiration'] = startup_projects[row['Project']]
            elif row['MRI?']:
                row['Share expiration'] = mri_projects[row['Project']]
            else:
                row['Share expiration'] = 'n/a'

            writer.writerow(row)


if __name__ == '__main__':
    main()
