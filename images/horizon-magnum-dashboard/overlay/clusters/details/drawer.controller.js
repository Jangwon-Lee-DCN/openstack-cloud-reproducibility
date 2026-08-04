/* Compact status interpretation shared by each cluster row drawer. */
(function() {
  'use strict';
  angular.module('horizon.dashboard.container-infra.clusters')
    .controller('horizon.dashboard.container-infra.clusters.DrawerController', controller);

  controller.$inject = ['$scope'];

  function controller($scope) {
    var ctrl = this;
    ctrl.objLen = function(obj) {
      return obj && typeof obj === 'object' ? Object.keys(obj).length : 0;
    };
    ctrl.phase = function(item) {
      var status = (item && item.status) || '';
      if (/_FAILED$/.test(status)) { return 'Failed'; }
      if (/_COMPLETE$/.test(status)) { return 'Workload ready'; }
      if (item && (item.api_address || (item.master_addresses || []).length)) {
        return 'Infrastructure provisioning';
      }
      return /_IN_PROGRESS$/.test(status) ? 'Desired state reconciliation' : 'Request recorded';
    };
    $scope.$watch('item.status', angular.noop);
  }
})();
