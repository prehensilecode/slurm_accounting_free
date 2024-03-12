#!/usr/bin/env python3
import sys
import os
from os.path import basename
from pathlib import Path
from io import StringIO
import typing
import argparse
import re
import csv
import grp
import calendar
import fiscalyear
import decimal
import ldap3
import delorean
import datetime
from delorean import Delorean, epoch, parse
from decimal import Decimal
from operator import itemgetter
import subprocess
import weasyprint

from . import __version__

from distutils.util import strtobool

from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import COMMASPACE, formatdate

import smtplib

from dataclasses import dataclass
import numpy as np
import pandas as pd
import time


debug_p = False

smtpserver = "smtp.example.com"
rate = Decimal(0.0123)  # $ per SU
penny = Decimal("0.01")
decimal.getcontext().rounding = decimal.ROUND_HALF_UP
all_groups = {}
for g in grp.getgrall():
    all_groups[g.gr_name.casefold()] = g


@dataclass(frozen=True)
class PI:
    lastname: str
    firstname: str
    login: str
    email: str
    college: str
    dept: str
    is_active: bool
    # project_list: list[Project] = field(default_factory=list)
    # course_list: list[str] = field(default_factory=list)

    def __hash__(self):
        return hash((self.login, self.firstname, self.lastname))


class Project:
    def __init__(self, name, pi, is_class=False, is_mri=False, is_startup=False, share_expiration='', fundorg_code='xxxxxx-xxxx'):
        self.name = name
        self.pi = pi
        self.is_class = is_class
        self.is_mri = is_mri
        self.is_startup = is_startup
        self.share_expiration = share_expiration
        self.fundorg_code = fundorg_code

    def __hash__(self):
        return hash(self.name.lower())

    def __eq__(self, other):
        return self.__hash__() == other.__hash__()

    def __repr__(self):
        return f'Project(name={self.name}, pi="{self.pi.lastname}, {self.pi.firstname}", is_class={self.is_class}, is_mri={self.is_mri}, is_startup=self.is_startup, fundorg_code={self.fundorg_code})'


class UserUsage:
    """User usage in SU and dollars"""

    global rate

    def __init__(self, sreport_line):
        self.project = sreport_line["Account"].strip()
        self.login = sreport_line["Login"]
        self.fullname = sreport_line["Proper Name"]
        self.su = Decimal(float(sreport_line["Used"]))
        self.charge = self.su * rate

    def __repr__(self):
        return f"""UserUsage(project="{self.project}", login="{self.login}",
               fullname="{self.fullname}", su={self.su},
                charge={self.charge})"""


class PIUsage:
    """User usage in SU and dollars"""

    global rate

    def __init__(self, sreport_line):
        decimal.getcontext().rounding = decimal.ROUND_HALF_UP
        self.name = sreport_line["Account"]
        self.compute_su = Decimal(float(sreport_line["Used"]))
        self.compute_charge = self.compute_su * rate
        self.project_usage_list = []

    def __repr__(self):
        return f"""PIUsage(name="{self.name}", compute_su={self.compute_su},
            compute_charge={self.compute_charge},
            project_usage_list={self.project_usage_list})"""


class DiskUsage:
    """Storage usage in SU and dollars"""

    global rate

    def __init__(self, name: str, su=0.0):
        decimal.getcontext().rounding = decimal.ROUND_HALF_UP
        self.name = name
        self.su = Decimal(su)
        self.charge = self.su * rate

    def __repr__(self):
        return f'DiskUsage(name="{self.name}", su={self.su})'


class ComputeUsage:
    """Compute usage in SU and dollars"""

    global rate

    def __init(self, su=0.0):
        decimal.getcontext().rounding = decimal.ROUND_HALF_UP
        self.su = Decimal(su)
        self.charge = self.su * rate

    def __repr__(self):
        return f"ComputeUsage(su={self.su})"


class ProjectUsage:
    """Project usage in SU and dollars"""

    global rate

    def __init__(self, name='', compute_su=Decimal(0.0), disk_su=Decimal(0.0),
                 PI=None,
                 is_class=False, is_mri=False, is_startup=False, gets_credit=False,
                 share_expiration=None,
                 fundorg_code=None):
        decimal.getcontext().rounding = decimal.ROUND_HALF_UP
        self.name = name.strip().lower()
        self.compute_su = compute_su
        self.disk_su = disk_su
        self.compute_charge = self.compute_su * rate
        self.disk_charge = self.disk_su * rate
        self.su = self.compute_su + self.disk_su
        self.charge = self.compute_charge + self.disk_charge
        self.user_usage_list = []
        self.fundorg_code = fundorg_code
        self.pi = None
        self.is_class = is_class
        self.is_mri = is_mri
        self.is_startup = is_startup
        self.gets_credit = gets_credit
        self.share_expiration = ''

    def set_from_sreport_line(self, sreport_line):
        decimal.getcontext().rounding = decimal.ROUND_HALF_UP
        self.name = sreport_line["Account"].strip()
        self.compute_su = Decimal(float(sreport_line["Used"]))
        self.disk_su = Decimal(0.0)
        self.compute_charge = self.compute_su * rate
        self.disk_charge = self.disk_su * rate
        self.su = self.compute_su + self.disk_su
        self.charge = self.compute_charge + self.disk_charge
        self.user_usage_list = []
        self.fundorg_code = None
        self.pi_email = None
        self.is_class = False

    def set_disk_su(self, disk_su):
        self.disk_su = Decimal(disk_su)
        self.disk_charge = self.disk_su * rate
        self.su = self.disk_su + self.compute_su
        self.charge = self.disk_charge + self.compute_charge

    def set_compute_su(self, compute_su):
        self.compute_su = Decimal(compute_su)
        self.compute_charge = self.compute_su * rate
        self.su = self.disk_su + self.compute_su
        self.charge = self.disk_charge + self.compute_charge

    def __repr__(self):
        return f"""ProjectUsage(name="{self.name}", fundorg_code={self.fundorg_code},
            pi={self.pi},
            is_class={self.is_class},
            is_mri={self.is_mri},
            is_startup={self.is_startup},
            gets_credit={self.gets_credit},
            compute_su={self.compute_su},
            compute_charge={self.compute_charge},
            disk_su={self.disk_su},
            disk_charge={self.disk_charge},
            su={self.su}, charge={self.charge},
            user_usage_list={self.user_usage_list})"""


def write_html_header(reportfile, project, cluster):
    reportfile.write('<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional/EN"\n')
    reportfile.write('  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">\n')
    reportfile.write('<html xmlns="http://www.w3.org/1999/xhtml">\n')
    reportfile.write('  <head>\n')
    reportfile.write('    <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />\n')
    reportfile.write('    <style type="text/css">\n')
    reportfile.write('       @page { size: Letter landscape; }\n')
    reportfile.write('       body { font-size: 9pt; }\n')
    # reportfile.write('       h4   { font-size: 10pt; }\n')
    reportfile.write('       pre { font-size: 9pt; }\n')
    reportfile.write('       .rates { font-size: 85%; font-style: italic; }\n')
    reportfile.write('       .code { font-family: Monaco, "Courier New", monospace; }\n')
    reportfile.write('       .image .caption { font-size: 75%; font-style: italic; text-align: center; }\n')
    reportfile.write('       #projectmembers {\n')
    reportfile.write('          border-collapse: collapse;\n')
    reportfile.write('          width: 100%;\n')
    reportfile.write('       }')
    reportfile.write('       #projectmembers td, #projectmembers th {\n')
    reportfile.write('          border: 1px solid #ddd;\n')
    reportfile.write('          padding: 2px;\n')
    reportfile.write('       }\n')
    reportfile.write('       #projectmembers tr:nth-child(even){background-color: #f2f2f2;}\n')
    reportfile.write('       #projectmembers th {\n')
    reportfile.write('          padding-top: 6px;\n')
    reportfile.write('          padding-bottom: 6px;\n')
    reportfile.write('          text-align: left;\n')
    reportfile.write('          background-color: #4CAF50;\n')
    reportfile.write('          color: white;\n')
    reportfile.write('       }\n')
    reportfile.write('       #jobstats {\n')
    reportfile.write('          border-collapse: collapse;\n')
    reportfile.write('          width: 100%;\n')
    reportfile.write('       }')
    reportfile.write('       #jobstats td, #jobstats th {\n')
    reportfile.write('          border: 1px solid #ddd;\n')
    reportfile.write('          padding: 8px;\n')
    reportfile.write('       }\n')
    reportfile.write('       #jobstats tr:nth-child(even){background-color: #f2f2f2;}\n')
    reportfile.write('       #jobstats th {\n')
    reportfile.write('          padding-top: 12px;\n')
    reportfile.write('          padding-bottom: 12px;\n')
    reportfile.write('          text-align: left;\n')
    reportfile.write('          background-color: #4CAF50;\n')
    reportfile.write('          color: white;\n')
    reportfile.write('       }\n')
    reportfile.write('    </style>\n')
    reportfile.write(f'    <title>{cluster} Usage Report for {project}</title>\n')
    reportfile.write('  </head>\n')


def make_statement_header(project:str, usage, cur_period, cluster="MYCLUSTER", debug_p=False):
    global rate
    global penny

    if debug_p:
        print(f'DEBUG: make_statement_header: usage = {usage}')
        print(f'DEBUG: make_statement_header: usage.pi = {usage.pi}')

    is_class = usage.is_class
    is_mri = usage.is_mri
    is_startup = usage.is_startup
    share_expiration = usage.share_expiration
    fundorg_code = usage.fundorg_code
    pi_lastname = usage.pi.lastname
    pi_firstname = usage.pi.firstname
    pi_email = usage.pi.email

    if debug_p:
        print(f'DEBUG: make_statement_header(): project = {project}')
        print(f'DEBUG: make_statement_header(): cur_period = {cur_period}')
        print(f'DEBUG: make_statement_header(): cluster = {cluster}')

    report_str = f'<h4>{cluster} usage charges for period {cur_period.strftime("%B %Y")}</h4>\n'
    report_str += '<p>&nbsp;</p>\n'
    report_str += f'<table><tr><td>PI:</td>      <td>{pi_lastname}, {pi_firstname} <tt>&lt;{pi_email}&gt;</tt></td></tr>\n'
    report_str += f'<tr><td>Project:</td>        <td>{project}</td></tr>\n'
    report_str += f'<tr><td>Coursework?</td>     <td>{is_class}</td></tr>\n'
    report_str += f'<tr><td>MRI?</td>            <td>{is_mri}</td></tr>\n'
    report_str += f'<tr><td>Startup/Grant?</td>  <td>{is_startup}</td></tr>\n'
    report_str += f'<tr><td>Share (MRI/Startup/Grant) expiration:</td> <td>{share_expiration}</td></tr>\n'
    report_str += f'<tr><td>Fund-Org code:</td> <td><tt>{fundorg_code}</tt></td></tr></table>\n\n'

    report_str += '<p><br/></p>'
    report_str += f'<span class="rates"><table><tr><td colspan="2">Rate: ${float(rate):.4f} per SU</td></tr>'
    report_str += '<tr><td>&nbsp;</td><td>Standard compute: 1 SU per core-hour</td></tr>'
    report_str += '<tr><td>&nbsp;</td><td>Big memory compute: 68 SU per RAM TiB-hour</td></tr>'
    report_str += '<tr><td>&nbsp;</td><td>GPU compute: 43 SU per GPU device-hour</td></tr>'
    report_str += '<tr><td>&nbsp;</td><td>Storage: 1081 SU per TiB-month</td></tr>'
    report_str += '</table></span>\n\n'

    return report_str


def read_courses(courses_filename):
    courses = []
    with open(courses_filename, "r") as f:
        for l in f:
            courses.append(l.strip().lower())

    return courses


def read_pis(pis_file):
    """Return list of PIs"""
    global debug_p

    if debug_p:
        print(f'DEBUG: read_pis(): pis_file = {pis_file}')

    pis = []
    with open(pis_file, 'r') as csvfile:
        pis_reader = csv.DictReader(csvfile)
        for row in pis_reader:
            if debug_p:
                print(f'DEBUG: read_pis(): User ID = {row["Last Name"]}')

            if row['Last Name']:
                is_active = int(row['Active?'].strip().lower()) == 1
                pis.append(
                    PI(
                        lastname=row['Last Name'],
                        firstname=row['First Name'],
                        login=row['User ID'],
                        email=row['Email'],
                        college=row['College'],
                        dept=row['Department'],
                        is_active=is_active,
                    )
                )
            else:
                if debug_p:
                    print('DEBUG: read_pis(): found empty "Last name" field')
                return pis

    return pis


def read_fundorg_codes(fundorg_file, pis):
    """Return dict
    {project_name: {'Fund-Org code': fund_org_code,
                    'PI': pi,
                    'Class?': is_class,
                    'MRI?': is_mri,
                    'Startup/Grant?': is_startup},
                    'Monthly credit?': gets_credit},
                    'Share expiration': expiration_date
    }
    """
    global debug_p

    if debug_p:
        print(f'DEBUG: read_fundorg_codes(): reading {fundorg_file}')

    pis_em = pis_by_email(pis)

    fundorg_codes = {}
    with open(fundorg_file, 'r', encoding='utf-8-sig') as csvfile:
        fundorg_reader = csv.DictReader(csvfile)

        for row in fundorg_reader:
            if debug_p:
                print(f'DEBUG: read_fundorg_codes: row = {row}')

            if row['Project']:
                is_class = bool(strtobool(row['Class?']))
                is_mri = bool(strtobool(row['MRI?']))
                is_startup = bool(strtobool(row['Startup/Grant?']))
                gets_credit = bool(strtobool(row['Monthly credit?']))
                fundorg_codes[row['Project'].strip().lower()] = {
                        'Fund-Org code': row['Fund-Org code'],
                        'PI': pis_em[row['Email']],
                        'Class?': is_class,
                        'MRI?': is_mri,
                        'Startup/Grant?': is_startup,
                        'Monthly credit?': gets_credit,
                        'Share expiration': row['Share expiration']
                }

                if debug_p:
                    print(f'DEBUG: read_fundorg_codes(): {row["Project"]} {row["Fund-Org code"]}')
            else:
                if debug_p:
                    print('DEBUG: read_fundorg_codes(): found empty Project field')
                return fundorg_codes

    return fundorg_codes


def pis_by_lastname(pis):
    retval = {}
    for p in pis:
        lastname = p.lastname
        lastname_split_sp = lastname.split(' ')
        lastname_split_hy = lastname.split('-')
        if len(lastname_split_sp) == 2:
            lastname = ''.join(lastname_split_sp)
        elif len(lastname_split_hy) == 2:
            lastname = ''.join(lastname_split_hy)

        retval[lastname.lower()] = p
    return retval


def pis_by_login(pis):
    retval = {}
    for p in pis:
        retval[p.login] = p
    return retval


def pis_by_email(pis):
    retval = {}
    for p in pis:
        retval[p.email] = p
    return retval


# annoyance - the "-n/--noheader" option to sreport also drops the useful
#   field names line
def read_sreport(sreport_file):
    global debug_p
    global rate
    global penny

    sreport = []
    with open(sreport_file, 'r') as f:
        with StringIO() as csvio:
            count = 0
            for line in f:
                if count < 4:
                    # skip first 4 lines
                    count += 1
                    continue
                else:
                    csvio.write(line)

            csvio.seek(0)
            reader = csv.DictReader(csvio, delimiter='|')
            for line in reader:
                sreport.append(line)

    return sreport


def read_dufile(du_file):
    global debug_p
    global rate
    global penny

    du_list = []
    with open(du_file, 'r') as f:
        # lines are: usage (kB)  group_dir
        for line in f:
            du, grpdir = line.strip().split()
            du = int(du)
            project = str.lower(re.sub(r'Grp$', 'Prj', grpdir.split('/')[-1]))
            du_list.append({'Account': project, 'DU': du})

    return du_list


def get_storage_usage(year, month, reports_dir, pis, courses):
    """Returns dict
    * keys = project name
    * values = usage in SU
    """
    global debug_p
    global rate

    last_day_of_month = calendar.monthrange(year, month)[1]
    du_reports_dir = reports_dir / Path('disk_usage')

    decimal.getcontext().rounding = decimal.ROUND_HALF_UP

    if debug_p:
        print(f'DEBUG: get_storage_usage(): du_reports_dir = {du_reports_dir}')

    du_rate = 1081  # SU per TiB-month

    # rate in SU per kiB-day
    du_rate_kiBday = Decimal(du_rate / (last_day_of_month * 1073741824.0))

    if debug_p:
        print(f'DEBUG: get_storage_usage: year, month = {year}, {month}')
        print(f'DEBUG: get_storage_usage: last_day_of_month = {last_day_of_month}')
        print(f'DEBUG: get_storage_usage: du_rate_kiBday = {du_rate_kiBday}')

    full_weeks = set([7, 14, 21, 28])

    # Storage rate = 1081 SU per TiB-month

    # project_du is a dict:
    # - key = project name
    # - value = disk usage in SU
    project_du = {}

    with os.scandir(du_reports_dir) as it:
        for entry in it:
            if entry.is_file():
                if debug_p:
                    print(f'DEBUG: get_storage_usage - reading du file {entry.path} {type(entry.path)}')

                day = int(entry.path.split('/')[-1].split('.')[0].split('-')[-1])

                if debug_p:
                    print(f'DEBUG: get_storage_usage - day of month = {day}')

                du_list = read_dufile(entry)

                if day in full_weeks:
                    factor = Decimal(7.0)
                else:
                    factor = Decimal(last_day_of_month - 28)

                if debug_p:
                    print(f'DEBUG: get_storage_usage - factor = {factor}')

                for du in du_list:
                    if debug_p:
                        print(f'DEBUG: du line = {du}')

                    # compute usage in SU; DU is in kiB
                    if du['Account'] in project_du:
                        project_du[du['Account']] += du['DU'] * du_rate_kiBday * factor
                    else:
                        project_du[du['Account']] = du['DU'] * du_rate_kiBday * factor

                    if debug_p:
                        print( f'DEBUG: {du["Account"]} - storage SU = {project_du[du["Account"]]}')

    if debug_p:
        for k, v in project_du.items():
            print(f'DEBUG: Project: {k}')
            charge = Decimal(v * Decimal(rate))
            print(f'DEBUG: Storage usage (SU): {v:.4e}     Storage charge: ${charge:8.02f}')

    return project_du


def get_compute_usage(year, month, reports_dir, pis, courses):
    """Returns 3 dicts
    1) usage by PI
    2) usage by project
      * keys = project name
      * values = usage in SU
    3) usage by user in project
    """
    global debug_p
    global rate

    sreport_dir = reports_dir / Path('sreport')

    pis_ln = pis_by_lastname(pis)
    pis_lg = pis_by_login(pis)

    if debug_p:
        print('DEBUG: PIs by last name and by login')
        for k, v in pis_ln.items():
            print(k, v)
        print('- - - - - - -')
        for k, v in pis_lg.items():
            print(k, v)
        print('- - - - - - -')

    # Reports dir contains:
    # * files of sreport output for each PI
    # * subdirectory named "disk_usage" containing du output for each week
    pi_usage = {}
    project_usage = {}
    user_usage = {}
    with os.scandir(sreport_dir) as it:
        for entry in it:
            pi_name = None
            if entry.is_file():
                if debug_p:
                    print('DEBUG: reading sreport file {entry.path}')

                sreport = read_sreport(entry.path)

                if debug_p:
                    print('DEBUG: sreport ...')
                    for line in sreport:
                        print(line)
                    print('- - - - - - - - - - - - - - - - - - - - - - -')

                for line in sreport:
                    if line['Account'][0] != ' ':
                        # PI usage summary
                        pi_name = line['Account']
                        pi_username = pis_ln[pi_name].login
                        pi_usage[pi_username] = PIUsage(line)
                    elif line['Account'][1] != ' ':
                        # Project/Account usage summary
                        project_name = line['Account'].strip()
                        project_usage[project_name] = ProjectUsage()
                        project_usage[project_name].set_from_sreport_line(line)
                        pi_usage[pi_username].project_usage_list.append(project_usage[project_name])
                    else:
                        username = line['Login']
                        user_usage[username] = UserUsage(line)
                        project_usage[project_name].user_usage_list.append(user_usage[username])

    return pi_usage, project_usage, user_usage


def make_charge_summary(project_usage):
    global debug_p
    global rate

    # for project, usage in project_usage.items():
    pass


def make_charge_details(compute_su, compute_charge, disk_su, disk_charge, total_su, total_charge):
    global debug_p
    global rate
    global penny

    report_str  = f'<pre><b>             {"Usage (SU)":>12}            {"Charge":>9}</b>\n'
    report_str += f'Compute      {float(compute_su):>12.6e}           ${compute_charge.quantize(penny):>9,.2f}\n'
    report_str += f'Storage      {float(disk_su):>12.6e}           ${disk_charge.quantize(penny):>9,.2f}\n'
    report_str +=  '             ------------           ----------\n'
    report_str += f'<b>TOTAL        {float(total_su):>12.6e}           ${total_charge.quantize(penny):>9,.2f}</b>\n'
    report_str +=  '             ============           ==========</pre>\n'
    report_str += '\n'
    report_str += '\n'

    return report_str


def make_per_user_usage_maybe(usage):
    global debug_p
    global rate
    global penny

    report_str = '<b>Compute usage by user</b>'
    if usage.user_usage_list:
        if debug_p:
            print(f'user_usage_list = {usage.user_usage_list}')

        report_str += f'<pre><b>{"Name":<20} {"User ID":>12} {"Usage (SU)":>14} {"Charge":>14}</b>\n'
        for user_usage in usage.user_usage_list:
            if usage.is_class:
                report_str += f'{user_usage.fullname:<20} {user_usage.login:>12} {float(user_usage.su):>14.6e}     ${0.:>9,.2f}\n'
            else:
                report_str += f'{user_usage.fullname:<20} {user_usage.login:>12} {float(user_usage.su):>14.6e}     ${user_usage.charge.quantize(penny):>9,.2f}\n'
    else:
        report_str += '<pre>n/a\n'

    report_str += '</pre>\n<br>'

    return report_str


def make_user_list(project:str):
    global debug_p
    global all_groups

    if debug_p:
        print(f'DEBUG: make_user_list(): project = {project}')

    group = all_groups[re.sub(r'([a-zA-Z0-9][a-zA-Z0-9]*)prj', r'\1grp', project, flags=re.IGNORECASE)]

    unix_epoch = epoch(0)

    users_info = []

    # read username and password from file
    username = None
    password = None
    upat = re.compile(r'username')
    ppat = re.compile(r'password')
    with open('/secrets/ldap_readonly_account.txt', 'r') as pwfile:
        lines = pwfile.readlines()

        for l in lines:
            if upat.match(l):
                username = l.split(':')[1].strip()

            if ppat.match(l):
                password = l.split(':')[1].strip()


    server = ldap3.Server('myclusterhead.cm.cluster', port=636, use_ssl=True, get_info=ldap3.ALL)
    try:
        conn = ldap3.Connection(server, username, password, auto_bind=True)
        base_dn = "dc=cm,dc=cluster"
        search_scope = ldap3.SUBTREE

        for u in group.gr_mem:
            search_filter = f"(uid={u})"
            conn.search(search_base=base_dn,
                        search_scope=search_scope,
                        search_filter=search_filter,
                        attributes=['*']
                        )
            if debug_p:
                print(f'DEBUG: make_user_list(): found {len(conn.entries)} entries.')

            entry_dict = conn.entries[0].entry_attributes_as_dict
            dt = datetime.timedelta(days=entry_dict['shadowExpire'][0])
            exp_datestamp = unix_epoch + dt
            exp_date = exp_datestamp.datetime.strftime('%b %d, %Y')
            users_info.append({'SN': entry_dict['sn'][0],
                               'CN': entry_dict['cn'][0],
                               'Expiration date': exp_date,
                               'Inactive?': bool(int(entry_dict['shadowInactive'][0])),
                               'Login shell': entry_dict['loginShell'][0],
                               'Email': entry_dict['mail'][0]})
    except Exception as e:
        print(f'EXCEPTION: ldap error {e}')
        sys.exit(1)

    users_info_sorted = sorted(users_info, key=itemgetter('SN'))

    if debug_p:
        print(f'DEBUG: make_user_list(): group = {group}')

    report_str = '<h3>Project Members</h3>\n'
    report_str += '<table id="projectmembers">\n'
    report_str += '<tr>\n'
    report_str += '<th>&nbsp;</th>\n'
    report_str += '<th>Name</th>\n'
    report_str += '<th>Email</th>\n'
    # report_str += '<th>Status</th>\n'
    # report_str += '<th>Acct. expiration date</th>\n'
    report_str += '</tr>'
    counter = 1
    for u in users_info_sorted:
        ### XXX Both "Inactive?"" and "Expiration date" do not prevent logins
        if not u['Login shell'] == '/bin/false':
            surname = u["SN"].strip()
            fullname = u["CN"].strip()
            if surname in fullname:
                givenname = fullname.replace(surname, '').strip()
            report_str += '<tr>\n'
            report_str += f'<td>{counter}</td>\n'
            report_str += f'<td>{surname}, {givenname}</td>\n'
            report_str += f'<td>{u["Email"]}</td>\n'

            report_str += '</tr>'
            counter += 1
    report_str += '</table>\n'

    return report_str


def kib_to_gib(kibstr:str):
    global debug_p

    if debug_p:
        print(f'DEBUG: kib_to_gib(): type(kibstr) = {type(kibstr)} ; kibstr = {kibstr}')

    kib = 0.
    if isinstance(kibstr, str):
        if not kibstr.strip() == "" and not kibstr.strip().casefold() == "nan":
            kib = float(kibstr[:-1])

    return kib / 1048576.


def sacct_dt_to_timedelta(sacct_dt:str):
    # sacct time duration strings look like: 1-23:15:48 (day-hh:mm:ss)
    d = 0
    split_dt = sacct_dt.split('-')
    if len(split_dt) > 1:
        d = int(split_dt[0])

    h, m, s = (int(x) for x in split_dt[-1].split(':'))

    return datetime.timedelta(days=d, hours=h, minutes=m, seconds=s)


def wait_time(submit:str, start:str):
    global debug_p

    submit_time = parse(submit)
    start_time = parse(start)

    return start_time - submit_time


def make_job_stats(year: int, month: int, project: str):
    global debug_p

    # compute reporting period
    dt_oneday = datetime.timedelta(days=1)
    last_day = Delorean(datetime.datetime(year, month,
                                 calendar.monthrange(year, month)[1]),
                        timezone='UTC')

    period_start = f'{year}-{month:02d}-01-00:00:00'
    period_end = f'{year}-{month:02d}-{last_day.datetime.day}-23:59:59'

    if debug_p:
        print(f'DEBUG: make_job_stats(): dt_oneday = {dt_oneday}')
        print(f'DEBUG: make_job_stats(): last_day = {last_day}')

    csv.register_dialect('sacct', delimiter='|')

    #sacct_cmdline = f'sacct -P -o JobID%20,State,Submit,Start,Elapsed,TotalCPU,MaxVMSize,MaxDiskRead,MaxDiskWrite -T -S{period_start} -E{period_end} -A {project} -a'.split()
    sacct_cmdline = f'sacct -P -o JobID%20,State,Submit,Start,Elapsed,MaxVMSize -T -S{period_start} -E{period_end} -A {project} -a'.split()

    if debug_p:
        print(f'DEBUG: make_job_stats(): sacct_cmdline = {sacct_cmdline}', flush=True)

    report_str = '<h3>Job Statistics</h3>'

    try:
        sacct_results = subprocess.run(sacct_cmdline, capture_output=True)

        if sacct_results.returncode != 0:
            print(f'WARNING: sacct return code = {sacct_results.returncode}')
            print(f'    {sacct_results.stderr}')

        if debug_p:
            print(f'DEBUG: len(sacct_results.stdout) = {len(sacct_results.stdout)}')

        sacct_output = sacct_results.stdout

        jobs_df = pd.read_csv(StringIO(sacct_output.decode('utf-8')), dialect='sacct')

        # fix units
        jobs_df['Submit'] = pd.to_datetime(jobs_df['Submit'], format='%Y-%m-%dT%H:%M:%S')
        jobs_df['Start'] = pd.to_datetime(jobs_df['Start'], format='%Y-%m-%dT%H:%M:%S')
        jobs_df['Elapsed'] = jobs_df['Elapsed'].apply(sacct_dt_to_timedelta)
        jobs_df['MaxVMSize'] = jobs_df['MaxVMSize'].apply(kib_to_gib)

        # add wait time
        jobs_df['Wait time'] = jobs_df['Start'] - jobs_df['Submit']

        # rename columns
        jobs_df = jobs_df.rename(columns={'Elapsed': 'Wallclock', 'MaxVMSize': 'Virtual memory (GiB)'})


        n_jobs = len(jobs_df.index)
        report_str += f'<p>Number of jobs = {n_jobs:,}<br/>'

        if n_jobs > 0:
            # XXX must only take rows where the JobID ends in ".batch"
            batch_jobs_df = jobs_df[jobs_df['JobID'].str.endswith('.batch', na=False)]

            # Want stats based only on completed jobs
            completed_jobs_df = batch_jobs_df[(batch_jobs_df['State'] == 'COMPLETED')]

            # Also want stats on incomplete jobs
            incomplete_jobs_df = batch_jobs_df[(batch_jobs_df['State'] != 'COMPLETED')]

            n_completed = 0
            if not completed_jobs_df.empty:
                n_completed = len(completed_jobs_df.index)

            report_str += f'% of jobs completed successfully = {100. * float(n_completed) / float(n_jobs):.2f}%\n'
            report_str += '</p>'

            report_str += '<h4>Completed Jobs</h4>'
            report_str += f'<p>Number of completed jobs = {n_completed:,}</p>'

            if n_completed > 0:

                report_str += '<p><table id="jobstats">\n'
                report_str += '<tr>\n'
                report_str += ' <th>&nbsp;</th>\n'
                report_str += ' <th>Min.</th>\n'
                report_str += ' <th>Max.</th>\n'
                report_str += ' <th>Mean</th>\n'
                report_str += '</tr>\n'

                wanted_fields = ['Wait time', 'Wallclock', 'Virtual memory (GiB)']

                for field in wanted_fields:
                    report_str += f'<tr><td>{field}</td>'
                    if field == 'Virtual memory (GiB)':
                        report_str += f'<td>{completed_jobs_df[field].min():.2f}</td>'
                        report_str += f'<td>{completed_jobs_df[field].max():.2f}</td>'
                        report_str += f'<td>{completed_jobs_df[field].mean():.2f}</td></tr>'
                    else:
                        report_str += f'<td>{completed_jobs_df[field].min()}</td>'
                        report_str += f'<td>{completed_jobs_df[field].max()}</td>'
                        report_str += f'<td>{completed_jobs_df[field].mean()}</td></tr>'
                report_str += '</table></p>\n'

            n_incomplete = len(incomplete_jobs_df.index)
            report_str += '<h4>Incomplete Jobs</h4>'
            report_str += '<p><i>Jobs which may not have completed due to a variety of reasons: https://slurm.schedmd.com/sacct.html#SECTION_JOB-STATE-CODES</i></p>'
            report_str += '<p><i>Jobs which may not have completed due to <a href="https://slurm.schedmd.com/sacct.html#SECTION_JOB-STATE-CODES">a variety of reasons</a>.</i></p>'

            if n_incomplete > 0:

                report_str += f'<p>Number of incomplete jobs = {n_incomplete:,}</p>'

                report_str += '<p><table id="jobstats">\n'
                report_str += '<tr>\n'
                report_str += ' <th>&nbsp;</th>\n'
                report_str += ' <th>Min.</th>\n'
                report_str += ' <th>Max.</th>\n'
                report_str += ' <th>Mean</th>\n'
                report_str += '</tr>\n'

                wanted_fields = ['Wait time', 'Wallclock', 'Virtual memory (GiB)']

                for field in wanted_fields:
                    report_str += f'<tr><td>{field}</td>'
                    if field == 'Virtual memory (GiB)':
                        report_str += f'<td>{incomplete_jobs_df[field].min():.2f}</td>'
                        report_str += f'<td>{incomplete_jobs_df[field].max():.2f}</td>'
                        report_str += f'<td>{incomplete_jobs_df[field].mean():.2f}</td></tr>'
                    else:
                        report_str += f'<td>{incomplete_jobs_df[field].min()}</td>'
                        report_str += f'<td>{incomplete_jobs_df[field].max()}</td>'
                        report_str += f'<td>{incomplete_jobs_df[field].mean()}</td></tr>'
                report_str += '</table></p>\n'

    except Exception as e:
        print(f'EXCEPTION: make_job_stats(): {type(e)} - {e}')
        sys.exit(2)

    return report_str


def fy_months(year, month):
    ### return list of strings YYYYMM of all months in current FY, up to but not including
    ### given (year, month)

    # set up fiscalyear module
    fiscalyear.setup_fiscal_calendar(start_month=7)

    retlist = []
    if month < 7:
        # start from July of last year
        fy = fiscalyear.FiscalYear(year - 1)
    else:
        fy = fiscalyear.FiscalYear(year)

    sd = datetime.date.fromisoformat(f'{fy.start.year}-{fy.start.month:02d}-{fy.start.day:02d}')
    sd = datetime.datetime.combine(sd, datetime.datetime.min.time())
    ed = datetime.datetime(year=year, month=month, day=1) - datetime.timedelta(days=1)

    for stop in delorean.stops(freq=delorean.MONTHLY, timezone='US/Eastern', start=sd, stop=ed):
        retlist.append(f'{stop.date.year}{stop.date.month:02d}')

    return retlist


def make_ytd_report_maybe(year:int, month:int, usage:ProjectUsage, project:str, cluster:str):
    global debug_p
    global rate
    global penny

    decimal.getcontext().rounding = decimal.ROUND_HALF_UP

    # monthly reports for months not including month for which statement is being generated
    monthly_reports = []
    for yyyymm in fy_months(year, month):
        if debug_p:
            print(f'DEBUG: make_ytd_report_maybe(): yyyymm = {yyyymm}')
            monthly_reports.append(Path(f'./RCM/{yyyymm}/mycluster_charges_{yyyymm}.csv'))
        else:
            monthly_reports.append(Path(f'/ifs/sysadmin/RCM/{yyyymm}/mycluster_charges_{yyyymm}.csv'))

    if debug_p:
        for m in monthly_reports:
            print(f'DEBUG: make_ytd_report_maybe(): {m}')

    # NB there would not be a monthly report for last month (i.e the month for which
    # this statement is being generated)
    compute_ytd = usage.compute_charge
    storage_ytd = usage.disk_charge

    for mr in monthly_reports:
        if debug_p:
            print(f'DEBUG: make_ytd_report_maybe(): mr.exists == {mr.exists()}')

        if mr.exists():
            charges_df = pd.read_csv(mr, engine='python', encoding='ISO-8859-1')
            mask = (charges_df['Project'] == project)
            all_charges_df = charges_df[mask][['Project', 'CPU charge ($)', 'Storage charge ($)']]

            if debug_p:
                print(f'DEBUG: make_ytd_report_maybe(): all_charges_df.shape == {all_charges_df.shape}')

            if all_charges_df.shape[0]:
                if debug_p:
                    print(f'DEBUG: make_ytd_report_maybe(): CPU charge ($) = {all_charges_df["CPU charge ($)"].iloc[0]:9.2f}')
                    print(f'DEBUG: make_ytd_report_maybe(): Storage charge ($) = {all_charges_df["Storage charge ($)"].iloc[0]:9.2f}')

                compute_ytd += Decimal(all_charges_df['CPU charge ($)'].iloc[0]).quantize(penny)
                storage_ytd += Decimal(all_charges_df['Storage charge ($)'].iloc[0]).quantize(penny)

    compute_ytd = Decimal(compute_ytd).quantize(penny)
    storage_ytd = Decimal(storage_ytd).quantize(penny)

    report_str = '<b>Cumulative charges for current fiscal year</b>\n'
    report_str += f'<pre>Compute usage:                      ${compute_ytd:9.2f}\n'
    report_str += f'Storage usage:                      ${storage_ytd:9.2f}\n'
    report_str +=  '                                    ----------\n'
    report_str += f'<b>TOTAL CUMULATIVE CHARGE:            ${compute_ytd + storage_ytd:9.2f}</b>\n'
    report_str +=  '                                    ==========</pre>\n'

    return report_str


def make_project_statement_and_send_maybe(year:int, month:int, statements_dir:Path, project:str, usage:ProjectUsage, cluster:str, send_email_p:bool):
    global debug_p
    global rate
    global penny

    if debug_p:
        print(f'DEBUG: make_project_statement_and_send_maybe(): year={year}, month={month}, statements_dir={statements_dir}, project={project}, usage={usage}, cluster={cluster}')

    cur_period = datetime.datetime(year=year, month=month, day=1)

    compute_su = usage.compute_su
    compute_charge = None
    disk_su = usage.disk_su
    disk_charge = None
    total_su = usage.su
    total_charge = None

    if usage.is_class:
        fake_charge = Decimal(0.0)
        compute_charge = fake_charge
        disk_charge = fake_charge
        total_charge = fake_charge
    else:
        compute_charge = usage.compute_charge
        disk_charge = usage.disk_charge
        total_charge = usage.charge

    statement_fn = f'{project}_{year}{month:02d}.html'
    statement_pdf_fn = f'{project}_{year}{month:02d}.pdf'

    with open(statements_dir / statement_fn, 'w') as statement_file:
        write_html_header(statement_file, project, cluster)

        statement_header = make_statement_header(project, usage,
                                                 cur_period,
                                                 cluster,
                                                 debug_p)

        statement_file.write('<body>\n')
        statement_file.write(statement_header)

        charge_details = make_charge_details(compute_su, compute_charge,
                                             disk_su, disk_charge,
                                             total_su, total_charge)
        statement_file.write(charge_details)

        per_user_usage = make_per_user_usage_maybe(usage)
        statement_file.write(per_user_usage)

        #job_stats = make_job_stats(year=year, month=month, project=project)
        #statement_file.write(job_stats)

        ytd_charges = make_ytd_report_maybe(year=year, month=month, usage=usage, project=project, cluster='MYCLUSTER')
        statement_file.write(ytd_charges)

        user_list = make_user_list(project)
        statement_file.write(user_list)

        statement_file.write('</body>\n')
        statement_file.write('</html>')

    # generate PDF statement
    weasyprint.HTML(statements_dir / statement_fn).write_pdf(statements_dir / statement_pdf_fn)

    if send_email_p:
        send_email_statement(statements_dir / statement_pdf_fn, project, usage.pi, cluster, year, month)
        time.sleep(15)
    else:
        if debug_p:
            print(f'DEBUG: Not sending email statement to sysadmin in place of {usage.pi.email}')
        else:
            print(f'Not sending email statement to {usage.pi.email}')


def make_statements(year, month, reports_dir, project_usage, project_du, pis, cluster, send_email_p=False):
    global debug_p
    global rate
    global penny

    statements_dir = reports_dir / 'statements'

    if debug_p:
        print(f'DEBUG: make_statements() - statements_dir = {statements_dir}')
        print('DEBUG: make_statements() - pis =')
        for pi in pis:
            print(f'DEBUG:       {pi}')

    if not statements_dir.exists():
        os.mkdir(statements_dir)

    pis_em = pis_by_email(pis)

    if debug_p:
        print('DEBUG: make_statements()')
        print('DEBUG: pis_em = ')
        for pi in pis_em:
            print(f'DEBUG:     {pi}')

    fundorg_file = reports_dir / '..' / 'fundorg_codes.csv'
    fundorg_codes = read_fundorg_codes(fundorg_file, pis)

    if debug_p:
        print('DEBUG: make_statements(): fundorg_codes -')
        for k, v in fundorg_codes.items():
            print(f'DEBUG: fundorg - {k}, {v}')
        print('')

    # list for summary CSV to email to OR Finance
    # this is different from the Banner-format summary CSV
    summary_csv_fields = [
        'Year',
        'Month',
        'Cluster',
        'Last name',
        'First name',
        'Email',
        'Project',
        'Is class?',
        'Is MRI?',
        'Is startup/grant?',
        'Monthly credit?',
        'Share expiration',
        'Fund-Org code',
        'CPU charge ($)',
        'Storage charge ($)',
        'Total charge ($)',
    ]
    summary_csv_rows = []

    # project_du may have more projects than project_usage since
    # the projects may have data on disk, but not have run any jobs.
    # Conversely, project_du may have fewer projects than project_usage
    # since the group may not have a directory when an old OLDCLUSTER group
    # which was not transferred over was revived.
    # XXX try reading fundorg_codes.keys


    # no charge projects, e.g. Co-ops/Interns
    no_charge_prj = set(['internprj', 'sysadmins'])

    # exceptions are from defunct projects where group directories were
    # created on MYCLUSTER and have remained empty
    exception_prj = set(['exceptionprj'])

    ### XXX for project in fundorg_codes.keys():
    for project in project_du.keys():
        if (project not in no_charge_prj) and (project not in exception_prj):
            if (project not in exception_prj) and (project not in no_charge_prj) and fundorg_codes[project]['PI'].is_active:
                if project in project_usage:
                    project_usage[project].set_disk_su(project_du[project])
                else:
                    if debug_p:
                        print(f'DEBUG: make_statements() - adding new project - {project}')
                    project_usage[project] = ProjectUsage(name=project, disk_su=project_du[project])

                if not project_usage[project].fundorg_code:
                    project_usage[project].fundorg_code = fundorg_codes[project.strip().lower()]['Fund-Org code']

                if not project_usage[project].pi:
                    project_usage[project].pi = fundorg_codes[project.strip().lower()]['PI']

                project_usage[project].is_class = fundorg_codes[project.strip().lower()]['Class?']
                project_usage[project].is_mri = fundorg_codes[project.strip().lower()]['MRI?']
                project_usage[project].is_startup = fundorg_codes[project.strip().lower()]['Startup/Grant?']
                project_usage[project].gets_credit = fundorg_codes[project.strip().lower()]['Monthly credit?']
                project_usage[project].share_expiration = fundorg_codes[project.strip().lower()]['Share expiration']

    for project, usage in project_usage.items():
        if debug_p:
            print(f'DEBUG: make_statements() - making statement for {project}')
            print(f'DEBUG:    {project}, {usage}')

        make_project_statement_and_send_maybe(year, month, statements_dir, project, usage, cluster, send_email_p)

        row = {
                'Year': year,
                'Month': month,
                'Cluster': cluster,
                'Last name': usage.pi.lastname,
                'First name': usage.pi.firstname,
                'Email': usage.pi.email,
                'Project': project,
                'Is class?': usage.is_class,
                'Is MRI?': usage.is_mri,
                'Is startup/grant?': usage.is_startup,
                'Monthly credit?': usage.gets_credit,
                'Share expiration': usage.share_expiration,
                'Fund-Org code': usage.fundorg_code,
                }

        if usage.is_class:
            fake_charge = Decimal(0.0)
            row['CPU charge ($)'] = fake_charge
            row['Storage charge ($)'] = fake_charge
            row['Total charge ($)'] = fake_charge
        else:
            row['CPU charge ($)'] = float(usage.compute_charge.quantize(penny))
            row['Storage charge ($)'] = float(usage.disk_charge.quantize(penny))
            row['Total charge ($)'] = float(usage.charge.quantize(penny))

        summary_csv_rows.append(row)

    summary_df = pd.DataFrame(summary_csv_rows, columns=summary_csv_fields)

    if debug_p:
        print(f'make_statements(): summary_df.head(5) = \n{summary_df.head(5)}')
        print(f'make_statements(): summary_df.dtypes = \n{summary_df.dtypes}')
        print()

    # fix some datatypes
    summary_df['Cluster'] = summary_df['Cluster'].astype('string')
    summary_df['Last name'] = summary_df['Last name'].astype('string')
    summary_df['First name'] = summary_df['First name'].astype('string')
    summary_df['Email'] = summary_df['Email'].astype('string')
    summary_df['Project'] = summary_df['Project'].astype('string')
    summary_df['Share expiration'] = summary_df['Share expiration'].astype('string')

    # set the "n/a" expiration dates to np.NaN
    summary_df.loc[summary_df['Share expiration'] == 'n/a', 'Share expiration'] = np.NaN
    summary_df['Share expiration'] = pd.to_datetime(summary_df['Share expiration'], format='%Y-%m-%d')

    summary_df['Fund-Org code'] = summary_df['Fund-Org code'].astype('string')
    summary_df['CPU charge ($)'] = pd.to_numeric(summary_df['CPU charge ($)'])
    summary_df['Storage charge ($)'] = pd.to_numeric(summary_df['Storage charge ($)'])
    summary_df['Total charge ($)'] = pd.to_numeric(summary_df['Total charge ($)'])

    # sort by "Last name"
    summary_df.sort_values(by='Last name',
                           key=lambda col: col.str.lower(),
                           inplace=True)

    if debug_p:
        print(f'DEBUG: make_statements(): summary_df.head(10) = \n{summary_df.head(10)})')
        print(f'DEBUG: make_statements(): summary_df.dtypes = \n{summary_df.dtypes})')

    return summary_df, statements_dir


def make_summary_for_banner(year, month, reports_dir, summary_df):
    # Want the following fields:
    # Fund, Orgn, Account, Program, Activity, Location, Debit, Credit, Description (34 Characters maximum), Reference ID
    # Account - one of two values 1111, 2222
    # Program, Activity, Location - all blank
    # Description - surname ORGNAME Month Year, e.g. VogeleyORGNAME January 2023 XXX surnames are not unique
    # Reference ID - all ORGNAME0123

    #summary_csv_fields = [
    #    'Year',
    #    'Month',
    #    'Cluster',
    #    'Last name',
    #    'First name',
    #    'Email',
    #    'Project',
    #    'Is class?',
    #    'Is MRI?',
    #    'Is startup/grant?',
    #    'Monthly credit?',
    #    'Share expiration',
    #    'Fund-Org code',
    #    'CPU charge ($)',
    #    'Storage charge ($)',
    #    'Total charge ($)',
    #]

    statement_date = datetime.date.fromisoformat(f'{year}-{month:02d}-01')
    year_str = statement_date.strftime('%Y')
    month_str = statement_date.strftime('%b')

    # want rows with valid fund-org and non-zero charges
    nonzero_charges_df = summary_df[(summary_df['Fund-Org code'].str.match(pat=r'\d{6}\D\d{4}') & (summary_df['Total charge ($)'] > 0.))].copy(deep=True)
    nonzero_charges_df.reset_index(inplace=True, drop=True)

    # XXX possible future change - infer this from the Fund number: funds beginning with "1" get a credit
    # Apply monthly credit if applicable
    credit_mask = nonzero_charges_df['Monthly credit?'] == True
    nonzero_charges_df.loc[credit_mask, 'Total charge ($)'] = nonzero_charges_df['Total charge ($)'] - 100.

    # Pick only those with >0 charge
    nonzero_charges_df = nonzero_charges_df[nonzero_charges_df['Total charge ($)'] > 0.].copy(deep=True)

    # Pick only a subset of columns
    nonzero_charges_df = nonzero_charges_df[['Fund-Org code', 'Last name', 'First name', 'Project', 'Total charge ($)']].copy(deep=True)

    nonzero_charges_df.reset_index(inplace=True, drop=True)

    # XXX For some reason, one row has its '-' (hyphen) replaced by en-dash
    # probably due to the Excel export. So, split fund-org on non-numeric
    # character.
    fundorg_split_series = nonzero_charges_df['Fund-Org code'].str.split(r'\D', regex=True)
    fundorg_df = pd.DataFrame(fundorg_split_series.tolist(), columns=['Fund', 'Orgn'])

    # build the Banner dataframe
    # first, the debits
    # treat account, fund, org numbers as strings
    nonzero_charges_df[['Fund', 'Orgn']] = fundorg_df
    nonzero_charges_df['Account'] = '1111'
    nonzero_charges_df['Program'] = ''
    nonzero_charges_df['Activity'] = ''
    nonzero_charges_df['Location'] = ''
    nonzero_charges_df['Debit'] = nonzero_charges_df['Total charge ($)']
    nonzero_charges_df['Credit'] = np.NaN
    nonzero_charges_df['Description (35 Characters maximum)'] = (
            nonzero_charges_df['First name'].astype('string') + ' '
            + nonzero_charges_df['Last name'].astype('string')
            + ' ORGNAME ' + month_str + ' ' + year_str)
    nonzero_charges_df['Description (35 Characters maximum)'] = (
            nonzero_charges_df['Description (35 Characters maximum)'].str[:35])

    # this is f'ORGNAME{month:02d}{last_2_digits_of_year}'
    short_year = int(str(year)[2:])
    nonzero_charges_df['Reference ID'] = f'ORGNAME{month:02d}{short_year:02d}'

    # pick only certain columns
    banner_cols = ['Fund', 'Orgn', 'Account', 'Program', 'Activity',
                   'Location', 'Debit', 'Credit',
                   'Description (35 Characters maximum)', 'Reference ID']
    nonzero_charges_df = nonzero_charges_df[banner_cols].copy(deep=True)

    nonzero_charges_df.reset_index(inplace=True, drop=True)

    # make the credits rows
    credits_df = pd.DataFrame().reindex_like(nonzero_charges_df)

    credits_df['Credit'] = nonzero_charges_df['Debit']
    credits_df['Fund'] = '123456'
    credits_df['Orgn'] = '1234'
    credits_df['Account'] = '2222'
    credits_df['Description (35 Characters maximum)'] = (
            nonzero_charges_df['Description (35 Characters maximum)'])
    credits_df['Reference ID'] = nonzero_charges_df['Reference ID']

    banner_charges_df = pd.concat([nonzero_charges_df, credits_df])

    # convert a bunch of columns to string
    banner_charges_df['Fund'] = banner_charges_df['Fund'].astype('string')
    banner_charges_df['Orgn'] = banner_charges_df['Orgn'].astype('string')
    banner_charges_df['Account'] = banner_charges_df['Account'].astype('string')
    banner_charges_df['Program'] = banner_charges_df['Program'].astype('string')
    banner_charges_df['Activity'] = banner_charges_df['Activity'].astype('string')
    banner_charges_df['Location'] = banner_charges_df['Location'].astype('string')
    banner_charges_df['Description (35 Characters maximum)'] = (
        banner_charges_df['Description (35 Characters maximum)'].astype('string'))
    banner_charges_df['Reference ID'] = banner_charges_df['Reference ID'].astype('string')

    # convert $ amounts to numeric type
    banner_charges_df['Debit'] = pd.to_numeric(banner_charges_df['Debit'])
    banner_charges_df['Credit'] = pd.to_numeric(banner_charges_df['Credit'])

    banner_charges_df.reset_index(inplace=True, drop=True)

    if debug_p:
        print(f'DEBUG: make_summary_for_banner(): banner_charges_df.describe() = \n{banner_charges_df.describe()}')
        print(f'DEBUG: make_summary_for_banner(): banner_charges_df.dtypes = \n{banner_charges_df.dtypes}')
        print()

    # write out CSV with BOM and Windows line endings
    banner_csv_filename = reports_dir / f'orgname_banner_{year}{month:02d}.csv'
    banner_charges_df[banner_cols].to_csv(banner_csv_filename,
                                          encoding='utf-8-sig',
                                          lineterminator='\r\n',
                                          float_format='%.2f', index=False)

    return banner_csv_filename


def write_summary(year, month, reports_dir, summary_df):
    # write out charge summary CSV with BOM and Windows line endings
    summary_csv_filename = reports_dir / f'mycluster_charges_{year}{month:02d}.csv'
    summary_df.to_csv(summary_csv_filename, encoding='utf-8-sig',
                      lineterminator='\r\n',
                      float_format='%.2f', index=False)

    return summary_csv_filename


def read_email_addresses(email_file_path=None):
    # read a CSV: Description, Name, Email
    # return a dict: Description: (Name, Email)
    if not email_file_path:
        # use default
        email_file_path = '/ifs/sysadmin/RCM/email_addressees.csv'

    email_addrs = {}
    email_file = Path(email_file_path)
    with open(email_file) as ef:
        reader = csv.DictReader(ef)
        for row in reader:
            email_addrs[row['Description']] = {'Name': row['Name'], 'Email': row['Email']}

    return email_addrs


def send_email_statement(statement, project: str, pi, cluster: str, year: int, month: int):
    global debug_p
    global smtpserver

    period = datetime.date(year=year, month=month, day=1)
    period_str = period.strftime('%b %Y')

    if debug_p:
        print(f'DEBUG: send_email_statement() - statement = {statement}')
        print(f'DEBUG: send_email_statement() - project = {project}')
        print(f'DEBUG: send_email_statement() - pi = {pi}')
        print(f'DEBUG: send_email_statement() - cluster = {cluster}')
        print(f'DEBUG: send_email_statement() - year = {year}')
        print(f'DEBUG: send_email_statement() - month = {month}')
        print(f'DEBUG: send_email_statement() - period = {period}')

    email_addrs = read_email_addresses()

    sender_name = email_addrs['orgnamesupport']['Name']
    sender_email = email_addrs['orgnamesupport']['Email']
    send_from = f'{sender_name} <{sender_email}>'

    if debug_p:
        send_to_name = email_addrs["debug"]["Name"]
        send_to_email = email_addrs["debug"]["Email"]
    else:
        send_to_name = f'{pi.lastname}, {pi.firstname}'
        send_to_email = f'<{pi.email}>'

    send_to = f'{send_to_name} <{send_to_email}>'
    send_cc = []

    if debug_p:
        print(f'DEBUG: send_email_statement() - send_to = {send_to}')
        print(f'DEBUG: send_email_statement() - send_from = {send_from}')
        print(f'DEBUG: send_email_statement() - send_cc = {send_cc}')
        print(f'DEBUG: send_email_statement() - pi.lastname = {pi.lastname}')
        print(f'DEBUG: send_email_statement() - pi.firstname = {pi.firstname}')
        print(f'DEBUG: send_email_statement() - pi.email = {pi.email}')

    msg = MIMEMultipart()
    msg['From'] = send_from
    msg['To'] = send_to

    if send_cc:
        msg['Cc'] = COMMASPACE.join(send_cc)

    msg['Date'] = formatdate(localtime=True)
    msg['Subject'] = f'ORGNAME {cluster} - {project} account charges for {period_str}'

    message_body = f'Dear Dr. {pi.lastname}:\n\n'
    message_body += f'Attached, please find a report detailing your group’s usage of ORGNAME {cluster} for {period_str}.\n\n'
    message_body += 'Thank you.\n'

    msg.attach(MIMEText(message_body))

    with open(statement, 'rb') as f:
        part = MIMEApplication(f.read(), Name=basename(statement))

    # after file is closed
    part['Content-Disposition'] = f'attachment; filename="{basename(statement)}"'
    msg.attach(part)

    print(f'Sending email to {COMMASPACE.join([send_to] + send_cc)}')
    if debug_p:
        print('DEBUG: send_email_statement(): NOT SENDING EMAIL')
        print(f'DEBUG: send_email_statement(): send_from={send_from}, send_to={send_to}, send_cc={send_cc}')
        print(f'DEBUG: send_email_statement(): msg.as_string() = {msg.as_string()}')

    with smtplib.SMTP(smtpserver) as mailserver:
        mailserver.send_message(msg)


def send_summaries_to_research_office(summary_csv_filename, banner_csv_filename, cluster, year, month, send_email_p=False):
    global debug_p

    verbose_p = True
    period = datetime.date(year=year, month=month, day=1)
    period_str = period.strftime('%b %Y')

    email_addrs = read_email_addresses()

    sender_name = email_addrs['orgnamesupport']['Name']
    sender_email = email_addrs['orgnamesupport']['Email']
    send_from = f'{sender_name} <{sender_email}>'

    if debug_p:
        rec_name = email_addrs['debug']['Name']
        rec_email = email_addrs['debug']['Email']
    else:
        rec_name = email_addrs['orifinance']['Name']
        rec_email = email_addrs['orifinance']['Email']

    send_to = f'{rec_name} <{rec_email}>'

    cc_name = email_addrs['sysadmin']['Name']
    cc_email = email_addrs['sysadmin']['Email']
    send_cc = f'{cc_name} <{cc_email}>'

    if send_email_p:
        if verbose_p:
            print(f'Sending summary CSV to {send_to}')

        msg = MIMEMultipart()
        msg['From'] = send_from
        msg['To'] = send_to
        msg['Cc'] = send_cc
        msg['Date'] = formatdate(localtime=True)
        msg['Subject'] = f'ORGNAME {cluster} - charges summary for {period_str}'

        message_body = 'Dear FINANCE_OFFICER:\n\n'
        message_body += f'Attached, please find a report detailing ORGNAME {cluster} charges for {period_str}.\n\n'
        message_body += 'Regards,\n'
        message_body += '    MY NAME\n'

        msg.attach(MIMEText(message_body))

        with open(summary_csv_filename, 'rb') as f:
            part = MIMEApplication(f.read(), Name=basename(summary_csv_filename))

        # after file is closed
        part['Content-Disposition'] = f'attachment; filename="{basename(summary_csv_filename)}"'
        msg.attach(part)

        with open(banner_csv_filename, 'rb') as f:
            part = MIMEApplication(f.read(), Name=basename(banner_csv_filename))

        # after file is closed
        part['Content-Disposition'] = f'attachment; filename="{basename(banner_csv_filename)}"'
        msg.attach(part)

        with smtplib.SMTP(smtpserver) as mailserver:
            mailserver.send_message(msg)
    else:
        if verbose_p:
            print('Charges summary CSV not emailed')


def main():
    global debug_p
    global rate
    global penny

    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Debugging output')
    parser.add_argument('-e', '--email', action='store_true',
                        help='Actually send email (Default: DOES NOT send email)')
    parser.add_argument('-w', '--when', default=None,
                        help='Date for reporting in format YYYY-MM')
    parser.add_argument('-r', '--reports-prefix', default='/ifs/sysadmin/RCM',
                        help='Reports prefix')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')
    parser.add_argument('-V', '--version', action='store_true',
                        help='Show version')
    args = parser.parse_args()

    if args.version:
        print(f'slurm_accounting {__version__}')
        sys.exit(0)

    if args.debug:
        debug_p = True
        print(f'DEBUG: args = {args}')

    period_str = None
    if not args.when:
        today = Delorean()
        last_month = today - datetime.timedelta(days=(today.datetime.day + 1))
        period_str = last_month.date.strftime('%Y-%m')
    else:
        period_str = args.when

    year, month = [int(p) for p in period_str.split('-')]

    print(f'slurm_accounting: generating statements for {year}-{month:02d}')

    if debug_p:
        reports_dir = Path(f'RCM/{year}-{month:02d}')
        print(f'DEBUG: main() - reports_dir = {reports_dir}')
    else:
        reports_dir = Path(f'{args.reports_prefix}/{year}-{month:02d}')

    if args.verbose:
        print(f'slurm_accounting: reports_dir = {reports_dir}')

    courses = read_courses(Path(f'{args.reports_prefix}') / 'courses.txt')
    if debug_p:
        print('DEBUG: courses = {courses}')
        print('')

    pis = read_pis(Path(f'{args.reports_prefix}') / 'myorg_pis.csv')
    if debug_p:
        print('DEBUG: pis')
        for p in pis:
            print(f'    {p}')
        print('')

    pi_usage, project_usage, user_usage = get_compute_usage(year, month, reports_dir, pis, courses)
    project_du = get_storage_usage(year, month, reports_dir, pis, courses)

    if debug_p:
        print('DEBUG: pi_usage -')
        for k, v in pi_usage.items():
            print(f'DEBUG: "{k}", {v}')
        print('')
        print('DEBUG: project_usage -')
        for k, v in project_usage.items():
            print(f'DEBUG: "{k}", {v}')
        print('')
        print('DEBUG: user_usage -')
        for k, v in user_usage.items():
            print(f'DEBUG: "{k}", {v}')
        print('')
        print('DEBUG: project_du -')
        for k, v in project_du.items():
            print(f'DEBUG: "{k}", {v}')

    cluster = 'MYCLUSTER'
    summary_df, statements_dir = make_statements(year, month, reports_dir,
                                                 project_usage, project_du,
                                                 pis, cluster, args.email)

    banner_csv_filename = make_summary_for_banner(year, month, reports_dir,
                                                  summary_df)

    summary_csv_filename = write_summary(year, month, reports_dir, summary_df)

    send_summaries_to_research_office(summary_csv_filename, banner_csv_filename,
                                      cluster, year, month, args.email)

if __name__ == '__main__':
    main()
