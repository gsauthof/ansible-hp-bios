This repository contains an [Ansible][2] module for gathering and
setting BIOS options on HP servers using the [conrep][1] utility.

2020, Georg Sauthoff <mail@gms.tf>

## Example

See the comments at the top of `library/conrep.py` for the module documentation
and some examples. Alternatively, you can execute `ansible-doc -M library conrep`
in this directory to view the module's documentation.

Sneak preview example task:

```
- name: apply low-latency settings
  conrep:
      settings:
          Intel_Turbo_Boost_Optimization_Gen8: Disabled
          PowerMonitoring: Disabled
```

## Getting Started

This module can be placed somewhere in the Ansible module search path. For example, in
the `library` directory relative to your Ansible playbook or role.

## See Also

[Serverfault answer that includes some links to HP low-latency guides][3] and examples of
how to change BIOS settings with conrep and hprcu tools.


[1]: https://support.hpe.com/hpesc/public/docDisplay?docId=emr_na-a00007607en_us#N10380
[2]: https://en.wikipedia.org/wiki/Ansible_(software)
[3]: https://serverfault.com/a/1011773/63769
