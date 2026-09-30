#!/usr/bin/env python3
"""Validate the queue scrape boundary; no cluster access or mutations."""
import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


class RabbitQueueScrapeTests(unittest.TestCase):
    def setUp(self):
        documents = list(yaml.safe_load_all((ROOT / 'manifests/native-service-monitors.yaml').read_text()))
        self.monitor = next(d for d in documents if d['metadata']['name'] == 'openstack-rabbitmq')
        self.aggregate, self.queue = self.monitor['spec']['endpoints']

    def test_existing_dashboard_source_unchanged(self):
        self.assertEqual(self.aggregate, {'port': 'metrics', 'interval': '30s', 'scrapeTimeout': '10s'})
        self.assertEqual(self.monitor['spec']['namespaceSelector'], {'matchNames': ['openstack']})
        self.assertEqual(self.monitor['spec']['selector']['matchLabels'], {'application': 'rabbitmq', 'component': 'server'})

    def test_verified_310_families_and_bounded_cadence(self):
        self.assertEqual(self.queue['path'], '/metrics/detailed')
        self.assertEqual(self.queue['params']['family'], [
            'queue_coarse_metrics', 'queue_metrics', 'channel_queue_metrics',
            'channel_queue_exchange_metrics'])
        self.assertEqual((self.queue['interval'], self.queue['scrapeTimeout']), ('30s', '10s'))
        self.assertNotIn('vhost', self.queue['params'])  # Do not silently omit service vhosts.

    def test_source_health_is_distinct_without_losing_identity_join(self):
        labels = {'job': 'rabbitmq', 'endpoint': 'metrics', 'namespace': 'openstack',
                  'pod': 'rabbitmq-rabbitmq-0', 'instance': '10.0.0.1:15692'}
        for rule in self.queue['relabelings']:
            self.assertNotIn('sourceLabels', rule)
            labels[rule['targetLabel']] = rule['replacement']
        self.assertEqual(labels, {'job': 'rabbitmq-queues', 'endpoint': 'queue-metrics',
                                 'namespace': 'openstack', 'pod': 'rabbitmq-rabbitmq-0',
                                 'instance': '10.0.0.1:15692'})

    def test_generic_identity_and_aggregate_samples_cannot_duplicate(self):
        rule, = self.queue['metricRelabelings']
        self.assertEqual(rule['sourceLabels'], ['__name__'])
        self.assertEqual(rule['action'], 'keep')
        names = ['rabbitmq_identity_info', 'rabbitmq_build_info',
                 'rabbitmq_queue_messages_ready', 'telemetry_scrape_size_bytes_count',
                 'rabbitmq_detailed_queue_messages_ready',
                 'rabbitmq_detailed_channel_messages_acked_total',
                 'rabbitmq_detailed_queue_messages_published_total']
        retained = [name for name in names if re.fullmatch(rule['regex'], name)]
        self.assertEqual(retained, names[-3:])


if __name__ == '__main__':
    unittest.main()
