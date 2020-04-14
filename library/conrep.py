#!/usr/bin/python
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: © 2020 Georg Sauthoff <mail@gms.tf>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function, unicode_literals

ANSIBLE_METADATA = {
    'metadata_version': '1.1',
    'status': ['preview'],
    'supported_by': 'community'
}

DOCUMENTATION = '''
---
module: conrep

short_description: Change HP BIOS settings with conrep

version_added: "2.9"

description:
    - requires the conrep command to be available on the remote system
    - conrep is part of the hp-scripting-tools package (cf. https://downloads.linux.hpe.com/SDR/repo/stk)
    - setting some advanced options require a custom hardware definition file (cf. https://serverfault.com/a/1011773/63769)

options:
    conrep:
        description:
            - Conrep executable (name or absolute path)
        default: conrep
    facts:
        description:
            - Return settings as facts
        default: true
    hwdef:
        description:
            - Conrep hardware definition file
        default: /opt/hp/hp-scripting-tools/etc/conrep.xml
    settings:
        description:
            - Dictionary of BIOS Settings. For available keys /Conrep/Section/@name values
              in a Conrep system configuration data dump. 
    settings_xml:
        description:
            - Raw Conrep setting XML as string. If specified takes precedence over
              the settings key.

author:
    - Georg Sauthoff (@gsauthof)
'''

EXAMPLES = '''
# Just gather facts
- name: gather BIOS settings
  conrep:

- name: disable system management interrupts
  conrep:
      settings:
          PowerMonitoring: Disabled

# just some settings without gathering facts
- name: apply low-latency settings
  conrep:
      conrep: /usr/local/bin/conrep
      hwdef: /usr/local/etc/conrep.xml
      facts: no
      settings:
          Intel_Turbo_Boost_Optimization_Gen8: Disabled
          PowerMonitoring: Disabled

# read settings from an existing XML file
- name: apply BIOS settings from file
  conrep:
      settings_xml: "{{ lookup('file', 'low-latency.dat') }}"
'''

RETURN = '''
diff:
    description: Difference between previous configuration and new configuration
    returned: always
    type: dict
    sample: {}
ansible_facts:
  description: facts to add to ansible_facts
  returned: always
  type: complex
  contains:
    conrep:
      description:
        - Dictonary of BIOS settings
      returned: when facts parameter is true
      type: dict
      sample: {}
'''

from ansible.module_utils.basic import AnsibleModule

import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


class ConrepError(RuntimeError):
    pass

def parse_dat(doc):
    r = doc.getroot()
    h = {}
    for e in r:
        if e.tag != 'Section':
            continue
        k = e.get('name')
        if e:
            if sys.version_info[0] < 3:
                v = ''.join(ET.tostring(x) for x in e)
            else:
                v = ''.join(ET.tostring(x, encoding='unicode') for x in e)
        else:
            v = e.text
        h[k] = v
    return h

def parse_dat_from_string(s):
    d = ET.ElementTree(ET.fromstring(s))
    return parse_dat(d)

def parse_dat_from_filename(filename):
    d = ET.parse(filename)
    return parse_dat(d)

def call_conrep(params, extra_args):
    p = subprocess.Popen([params['conrep'], '-x', params['hwdef']] + extra_args,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
    o, e = p.communicate()
    if p.returncode != 0:
        raise ConrepError('Conrep failed (rc={}): {} {}'.format(p.returncode, o, e))

def read_settings(params):
    with tempfile.NamedTemporaryFile() as f:
        call_conrep(params, ['-f', f.name, '-s'])
        return parse_dat_from_filename(f.name)

def write_settings(params, settings, check_mode, debug=False):
    with tempfile.NamedTemporaryFile('r+') as f:
        print('<Conrep>', file=f)
        for k, v in settings.items():
            print('<Section name="{}">{}</Section>'.format(k, v), file=f)
        print('</Conrep>', file=f)
        f.flush()
        if not check_mode:
            call_conrep(params, ['-f', f.name, '-l'])
        if debug:
            f.seek(0)
            return f.read()

def check_settings(old_settings, settings):
    for k, v in settings.items():
        if k not in old_settings:
            raise ConrepError(("Setting '{}' (value: {}) isn't known"
                " by conrep - perhaps you need a special hardware "
                "definition file?").format(k, v))

def filter_changed_settings(old_settings, settings):
    h = {}
    for k, v in settings.items():
        if v != old_settings[k]:
            h[k] = v
    return h

def diff_settings(old_settings, settings):
    before = []
    after = []
    for k, v in sorted(settings.items()):
        before.append('{} => {}'.format(k, old_settings[k]))
        after.append('{} => {}'.format(k, v))
    before.append('')
    after.append('')
    return { 'before': '\n'.join(before), 'after': '\n'.join(after) }

def merge_dicts(xs, ys):
    r = xs.copy()
    r.update(ys)
    return r

def run_module():
    module_args = dict(
        conrep       = dict(type='str',  required=False, default='conrep'),
        facts        = dict(type='bool', required=False, default=True),
        hwdef        = dict(type='str',  required=False,
                          default='/opt/hp/hp-scripting-tools/etc/conrep.xml'),
        settings     = dict(type='dict', required=False, default=dict()),
        settings_xml = dict(type='str', required=False, default=''),
    )

    result = dict(
        changed       = False,
        ansible_facts = dict(),
    )

    module = AnsibleModule(
        argument_spec       = module_args,
        supports_check_mode = True
    )
    debug = module._verbosity >= 3

    try:
        if module.params['settings_xml']:
            settings = parse_dat_from_string(module.params['settings_xml'])
        else:
            settings = module.params['settings']
        old_settings = read_settings(module.params)

        check_settings(old_settings, settings)
        settings = filter_changed_settings(old_settings, settings)
        if module._diff:
            result['diff'] = diff_settings(old_settings, settings)

        if settings:
            t = write_settings(module.params, settings, module.check_mode, debug)
            if debug:
                result['debug'] = 'generated conrep.dat: {}'.format(t)
            result['changed'] = True

        if module.params['facts']:
            result['ansible_facts']['conrep'] = merge_dicts(old_settings, settings)
    except ConrepError as e:
        module.fail_json(msg = str(e), **result)

    module.exit_json(**result)

def main():
    run_module()

if __name__ == '__main__':
    main()


