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
module: hprcu

short_description: Change HP BIOS settings with hprcu

version_added: "2.9"

description:
    - requires the hprcu command to be available on the remote system
    - hprcu is part of the hp-scripting-tools package (cf. https://downloads.linux.hpe.com/SDR/repo/stk)

options:
    hprcu:
        description:
            - Hprcu executable (name or absolute path)
        default: hprcu
    facts:
        description:
            - Return settings as facts
        default: true
    settings:
        description:
            - Dictionary of BIOS Settings. For available keys see
              /hprcu/feature/feature_name text in a Hprcu system configuration
              data dump. 
    settings_xml:
        description:
            - Raw Hprcu setting XML as string. If specified takes precedence over
              the settings key.

author:
    - Georg Sauthoff (@gsauthof)
'''

EXAMPLES = '''
# Just gather facts
- name: gather BIOS settings
  hprcu:

- name: disable system management interrupts
  hprcu:
      settings:
          "Processor Power and Utilization Monitoring": Disabled

# just some settings without gathering facts
- name: apply low-latency settings
  hprcu:
      hprcu: /usr/local/bin/hprcu
      facts: no
      settings:
          "Intel(R) Hyperthreading Options": Disabled
          "Processor Power and Utilization Monitoring": Disabled

# read settings from an existing XML file
- name: apply BIOS settings from file
  hprcu:
      settings_xml: "{{ lookup('file', 'low-latency.xml') }}"
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
        hprcu:
            description:
                - Dictonary of BIOS settings
            returned: when facts parameter is true
            type: dict
            sample: {}
'''

from ansible.module_utils.basic import AnsibleModule
from ansible.utils.vars import merge_hash

import copy
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from io import BytesIO

class HprcuError(RuntimeError):
    pass

def doc2string(d):
    f = BytesIO()
    d.write(f)
    return f.getvalue().decode()

def et_tostring(e):
    if sys.version_info[0] < 3:
        return ET.tostring(e)
    else:
        return ET.tostring(e, encoding='unicode')

def apply_settings(doc, h):
    changed = False
    seen = set()
    r = doc.getroot()
    for f in r:
        if f.tag != 'feature':
            continue
        name = f.find('feature_name').text
        if name in h:
            seen.add(name)
            v = h[name]
            if f.get('feature_type') == 'option':
                oids = [ o.get('option_id') for o in f if o.tag == 'option'
                                        and o.find('option_name').text == v ]
                if not oids:
                    x = et_tostring(f)
                    raise HprcuErrror(('Selected value {} for option {} '
                        'unknown by hprcu ({})').format(v, n.text, x))
                changed = changed or f.get('selected_option_id') != oids[0]
                f.set('selected_option_id', oids[0])
            elif f.get('feature_type') == 'string':
                fv = f.find('feature_value')
                changed = changed or fv.text != v
                fv.text = v
            else:
                raise HprcuError(('Unknown feature type {}'
                    ' of feature {}').format(f.get('feature_type'), n.text))
    if len(seen) != len(h):
        raise HprcuError('Some features are unknown to this hprcu: {}'
                .format(', '.join(x for x in h if x not in seen)))
    return changed

def doc2dict(doc):
    h = {}
    r = doc.getroot()
    for f in r:
        if f.tag != 'feature':
            continue
        if f.get('feature_type') == 'option':
            h[f.get('feature_id')] = f.get('selected_option_id')
        elif f.get('feature_type') == 'string':
            h[f.get('feature_id')] = f.find('feature_value').text
    return h

def doc2facts(doc):
    h = {}
    if not doc:
        return h
    r = doc.getroot()
    for f in r:
        if f.tag != 'feature':
            continue
        k = f.find('feature_name').text
        if f.get('feature_type') == 'option':
            v = f.find('option[@option_id="{}"]/option_name'.format(
                               f.get('selected_option_id'))).text
        elif f.get('feature_type') == 'string':
            v = f.find('feature_value').text
        else:
            continue
        h[k] = v
    return h

def doc_yield_changes(old_doc, doc):
    x = doc2dict(old_doc)
    y = doc2dict(doc)
    for k, v in y.items():
        if k not in x:
            raise HprcuError('Feature {} not known by this hprcu'.format(k))
        if x[k] != v:
            return True
    return False

def mk_diff(old_doc, doc):
    h = {}
    h['before'] = doc2string(old_doc)
    h['after']  = doc2string(doc)
    return h


def call_hprcu(params, extra_args):
    p = subprocess.Popen([params['hprcu'], '-a' ] + extra_args,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
    o, e = p.communicate()
    if p.returncode != 0:
        raise HprcuError('hprcu failed (rc={}): {} {}'.format(p.returncode, o, e))

def read_settings(params):
    with tempfile.NamedTemporaryFile() as f:
        call_hprcu(params, ['-f', f.name, '-s'])
        return ET.parse(f.name)

def write_settings(params, doc, check_mode):
    with tempfile.NamedTemporaryFile() as f:
        doc.write(f)
        f.flush()
        if not check_mode:
            call_hprcu(params, ['-f', f.name, '-l'])


def diff_settings(old_settings, settings):
    before = []
    after = []
    for k, v in sorted(settings.items()):
        before.append('{} => {}'.format(k, old_settings[k]))
        after.append('{} => {}'.format(k, v))
    before.append('')
    after.append('')
    return '\n'.join(before), '\n'.join(after)

def run_module():
    module_args = dict(
        hprcu        = dict(type='str',  required=False, default='hprcu'),
        facts        = dict(type='bool', required=False, default=True),
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
        changed = False
        old_doc = read_settings(module.params)
        doc = None
        if module.params['settings']:
            doc = copy.deepcopy(old_doc)
            changed = apply_settings(doc, module.params['settings'])
        if module.params['settings_xml']:
            doc = ET.ElementTree(ET.fromstring(module.params['settings_xml']))
            changed = doc_yield_changes(old_doc, doc)

        if module._diff:
            result['diff'] = mk_diff(old_doc, doc)

        if changed:
            write_settings(module.params, doc, module.check_mode)
            if debug:
                result['debug'] = 'new hprcu.xml: {}'.format(
                        doc2string(doc) if doc else '')
            result['changed'] = True

        if module.params['facts']:
            result['ansible_facts']['hprcu'] = doc2facts(doc if doc else old_doc)

    except HprcuError as e:
        module.fail_json(msg = str(e), **result)

    module.exit_json(**result)

def main():
    run_module()

if __name__ == '__main__':
    main()


