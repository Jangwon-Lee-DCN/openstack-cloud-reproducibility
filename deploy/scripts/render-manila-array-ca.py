"""Render an explicit, fingerprint-approved private array CA override; no apply."""
import argparse
import base64
import configparser
import copy
import hashlib
from pathlib import Path
import re
import ssl

import yaml


def compose(base, addition):
    """Preserve existing values and reject ambiguous list ownership collisions."""
    if not isinstance(base, dict):
        raise ValueError('Base values must be a mapping')
    result = copy.deepcopy(base)
    for key, value in addition.items():
        prior = result.get(key)
        if isinstance(value, dict):
            result[key] = compose({} if prior is None else prior, value)
        elif isinstance(value, list):
            if prior is None:
                prior = []
            if not isinstance(prior, list) or any(not isinstance(item, dict) for item in prior):
                raise ValueError('Structured list values required for safe CA composition')
            for item in value:
                name = item.get('name', item.get('metadata', {}).get('name'))
                matches = [old for old in prior if old.get('name', old.get('metadata', {}).get('name')) == name
                           or ('mountPath' in item and old.get('mountPath') == item['mountPath'])]
                if matches:
                    if len(matches) != 1 or matches[0] != item:
                        raise ValueError('Existing resource or mount conflicts with CA settings')
                else:
                    prior.append(copy.deepcopy(item))
            result[key] = prior
        else:
            result[key] = value
    return result


def merge_values(base, override):
    """Merge ordered Helm input mappings; lists are replaced before CA composition."""
    if not isinstance(base, dict) or not isinstance(override, dict):
        raise ValueError('Values inputs must be mappings')
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_values(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def render(pem, expected, base=None):
    normalized = expected.replace(':', '').lower()
    if not re.fullmatch(r'[0-9a-f]{64}', normalized):
        raise ValueError('Explicit SHA256 certificate fingerprint required')
    if pem.count('-----BEGIN CERTIFICATE-----') != 1 or pem.count('-----END CERTIFICATE-----') != 1:
        raise ValueError('Exactly one approved CA certificate required')
    der = ssl.PEM_cert_to_DER_cert(pem.strip())
    digest = hashlib.sha256(der).hexdigest()
    if digest != normalized:
        raise ValueError('Certificate differs from approved fingerprint')
    ssl.create_default_context(cadata=pem)
    directory = '/etc/manila/array-ca'
    override = '[powerstore]\ndell_ssl_cert_verify = true\ndell_ssl_cert_path = '+directory+'/ca.pem\n'
    # Immutable object identity must cover the policy file as well as the CA.
    name = 'manila-array-ca-' + hashlib.sha256((pem+override).encode()).hexdigest()[:32]
    addition = {
        'extraObjects': [{'apiVersion': 'v1', 'kind': 'ConfigMap',
                          'metadata': {'name': name}, 'immutable': True,
                          'data': {'ca.pem': pem, '99-powerstore-trust.conf': override}}],
        'pod': {'mounts': {'manila_share': {'manila_share': {
            'volumes': [{'name': 'array-ca', 'configMap': {'name': name, 'defaultMode': 0o644}},
                        {'name': 'array-ca-config', 'configMap': {'name': name, 'defaultMode': 0o644}}],
            'volumeMounts': [{'name': 'array-ca', 'mountPath': directory, 'readOnly': True},
                            {'name': 'array-ca-config',
                             'mountPath': '/etc/manila/manila.conf.d/99-powerstore-trust.conf',
                             'subPath': '99-powerstore-trust.conf', 'readOnly': True}],
        }}}},
    }
    return compose({} if base is None else base, addition)


def verify_rendered(objects, pem, expected):
    """Verify delivered trust in Helm output without returning secret contents."""
    desired = render(pem, expected)
    ca = desired['extraObjects'][0]
    def one(kind, name):
        matches = [obj for obj in objects if obj.get('kind') == kind
                   and obj.get('metadata', {}).get('name') == name]
        if len(matches) != 1:
            raise ValueError('Required Manila rendered object missing or duplicated')
        return matches[0]
    actual = one('ConfigMap', ca['metadata']['name'])
    if actual.get('immutable') is not True or actual.get('data') != ca['data']:
        raise ValueError('Rendered array CA differs from approved immutable input')
    try:
        conf = configparser.ConfigParser(interpolation=None, strict=False)
        conf.read_string(base64.b64decode(one('Secret', 'manila-etc')['data']['manila.conf'],
                                         validate=True).decode())
        conf.read_string(actual['data']['99-powerstore-trust.conf'])
        if (not conf.getboolean('powerstore', 'dell_ssl_cert_verify')
                or conf.get('powerstore', 'dell_ssl_cert_path') != '/etc/manila/array-ca/ca.pem'):
            raise ValueError()
    except Exception:
        raise ValueError('Rendered Manila array TLS configuration is not qualified') from None
    deployment = one('Deployment', 'manila-share')
    if deployment['spec'].get('replicas') != 1 or deployment['spec'].get('strategy') != {'type': 'Recreate'}:
        raise ValueError('Rendered share-manager may overlap during replacement')
    pod = deployment['spec']['template']['spec']
    containers = [c for c in pod['containers'] if c['name'] == 'manila-share']
    mounts = desired['pod']['mounts']['manila_share']['manila_share']
    if (len(containers) != 1
            or any(pod.get('volumes', []).count(v) != 1 for v in mounts['volumes'])
            or any(containers[0].get('volumeMounts', []).count(v) != 1 for v in mounts['volumeMounts'])):
        raise ValueError('Rendered Manila share CA volume or read-only mount differs')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ca', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--base-values', action='append', default=[],
                        help='Ordered existing values, repeatable; output may contain their secrets')
    args = parser.parse_args()
    base = {}
    for path in args.base_values:
        base = merge_values(base, yaml.safe_load(Path(path).read_text()))
    print(yaml.safe_dump(render(Path(args.ca).read_text(), args.sha256, base), sort_keys=False))
