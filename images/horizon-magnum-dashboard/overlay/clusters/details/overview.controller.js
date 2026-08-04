/* DCN managed-Kubernetes operational detail model. */
(function() {
  'use strict';

  angular.module('horizon.dashboard.container-infra.clusters')
    .controller('ClusterOverviewController', ClusterOverviewController);

  ClusterOverviewController.$inject = [
    '$scope',
    'horizon.app.core.openstack-service-api.magnum'
  ];

  function ClusterOverviewController($scope, magnum) {
    var ctrl = this;
    ctrl.cluster = {};
    ctrl.cluster_template = {};
    ctrl.timeline = [];
    ctrl.objLen = objLen;
    ctrl.isReady = false;
    ctrl.isBusy = false;
    ctrl.hasFailed = false;
    ctrl.repositoryPath = '';
    ctrl.compatibility = [];

    $scope.context.loadPromise.then(onGetCluster);

    function onGetCluster(cluster) {
      ctrl.cluster = cluster.data;
      ctrl.isReady = /^(CREATE|UPDATE|RESUME)_COMPLETE$/.test(ctrl.cluster.status || '');
      ctrl.isBusy = /_IN_PROGRESS$/.test(ctrl.cluster.status || '');
      ctrl.hasFailed = /_FAILED$/.test(ctrl.cluster.status || '');
      ctrl.repositoryPath = 'clusters/magnum-' + ctrl.cluster.id;
      ctrl.timeline = buildTimeline(ctrl.cluster);
      magnum.getClusterTemplate(ctrl.cluster.cluster_template_id).then(onGetClusterTemplate);
    }

    function onGetClusterTemplate(clusterTemplate) {
      ctrl.cluster_template = clusterTemplate.data;
      ctrl.compatibility = compatibility(ctrl.cluster_template);
    }

    function buildTimeline(cluster) {
      var status = cluster.status || '';
      var reason = (cluster.status_reason || '').toLowerCase();
      var complete = /_COMPLETE$/.test(status);
      var failed = /_FAILED$/.test(status);
      var active = 0;

      if (cluster.created_at) { active = 1; }
      if (cluster.updated_at || /CREATE|UPDATE/.test(status)) { active = 2; }
      if (cluster.api_address || (cluster.master_addresses || []).length) { active = 5; }
      if (complete) { active = 6; }
      if (failed) {
        active = /argo|git|repository|package/.test(reason) ? 2 :
          (/machine|capi|capo|nova|neutron|octavia|load.?balancer/.test(reason) ? 5 : 1);
      }

      return [
        phase(1, 'Request accepted', 'Magnum validated and recorded the request'),
        phase(2, 'Draft rendered', 'The desired-state package is written to staging'),
        phase(3, 'Approved for deployment', 'An independent policy review publishes the deployment revision'),
        phase(4, 'Argo CD reconciliation', 'The published package is synchronized into CAPI objects'),
        phase(5, 'Infrastructure provisioning', 'CAPO creates network, load balancer and machines'),
        phase(6, 'Workload ready', 'Kubernetes API and baseline add-ons are healthy')
      ];

      function phase(number, title, detail) {
        return {
          number: number,
          title: title,
          detail: detail,
          state: failed && number === active ? 'failed' :
            (number < active || (complete && number === active) ? 'complete' :
              (number === active ? 'active' : 'pending'))
        };
      }
    }

    function compatibility(template) {
      var labels = template.labels || {};
      return [
        check('Kubernetes version', labels.kube_tag || 'Defined by image/profile', !!labels.kube_tag),
        check('Network driver', template.network_driver || 'Not declared', !!template.network_driver),
        check('Storage integration', template.volume_driver || 'Cinder CSI add-on', true),
        check('API endpoint', template.master_lb_enabled === false ?
          'Direct endpoint (experimental)' : 'Octavia load balancer', template.master_lb_enabled !== false),
        check('Machine remediation', labels.auto_healing_enabled === 'true' ? 'Enabled' : 'Optional', true)
      ];
    }

    function check(name, value, supported) {
      return {name: name, value: value, supported: supported};
    }

    function objLen(obj) {
      return obj && typeof obj === 'object' ? Object.keys(obj).length : 0;
    }
  }
})();
