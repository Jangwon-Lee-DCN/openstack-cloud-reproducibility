# OpenStack P0 Track A ToDo — Core Orchestration & Compute

## 1. 문서 목적과 작업 경계

이 문서는 P0 기능을 세 개의 병렬 트랙으로 개발할 때 **Track A**가 소유할
작업 계약이다. Track A의 목표는 Nova·Neutron·Cinder 등 개별 OpenStack API를
대체하는 것이 아니라, 사용자가 요청한 장기 실행 작업을 일관된 방식으로
검증·추적·재시도하고 반복 가능한 Compute 구성을 배포하는 플랫폼 계층을
만드는 것이다.

Track A가 담당하는 범위는 다음 여섯 가지뿐이다.

1. 공통 Operation/Task API
2. 생성 전 Preflight/Dry-run 검증
3. Launch Template
4. Auto Scaling
5. Soft-delete/Recycle Bin
6. Deletion Protection

알림 채널, 비용, 백업/DR, 인증서/Secret rotation, 감사 검색, 네트워크 진단,
이미지 공급망, 태그 정책은 다른 트랙의 소유다. Track A는 이 기능을 직접
구현하지 않고 이벤트와 확장 인터페이스만 제공한다.

## 2. 현재 상태와 확인해야 할 갭

저장소에서 확인되는 사실과 개발 전에 운영 환경에서 다시 확인할 사항을
구분한다.

### 2.1 저장소에서 확인된 기반

- Magnum 등에는 개별 서비스의 비동기 수명주기와 일부 dry-run 성격의 검증이
  존재한다.
- VPC/프로젝트 facade 및 Horizon 확장 지점이 존재한다.
- Nova, Neutron, Cinder, Aodh, Ceilometer, Gnocchi 구성과 서비스별 모니터링
  자산이 존재한다.
- Region을 사용자가 선택하고 Rack/AZ는 Subnet과 대상 리소스로부터 플랫폼이
  결정한다는 계약은
  `docs/current-openstack-helm/19-region-subnet-placement-contract.md`에 정의돼
  있다.

### 2.2 이 트랙이 해소할 갭

현재 저장소 문서와 코드만으로는 다음을 **플랫폼 공통 계약으로 확인할 수
없다**. 이는 개별 OpenStack API에 유사 기능이 전혀 없다는 뜻이 아니며,
구현 착수 시 API·DB·운영 환경을 재조사해야 한다.

- 서비스 간 공통 Operation 상태, 오류 코드, idempotency 및 rollback 계약
- 생성 요청 전에 quota·정책·배치·주소·용량을 함께 판정하는 통합 preflight
- 버전이 고정된 재사용 가능 Launch Template와 immutable version 참조
- 템플릿과 Aodh/Telemetry를 연결한 일반 VM Auto Scaling 수명주기
- 여러 서비스 리소스에 공통 적용되는 휴지통과 보존기간
- 생성·수정·삭제 경로 전체에 적용되는 삭제 보호

Nova의 `soft_delete`, Heat의 stack, Senlin 설치 여부, 서비스별 tag/lock 기능은
구현 방식을 결정하기 전에 반드시 현 배포와 API microversion에서 확인한다.
특히 native 기능이 존재하더라도 이 문서의 공통 API 의미와 다르면 adapter로
감싸며, 같은 기능을 중복 구현하지 않는다.

## 3. 목표 토폴로지

```text
User / CLI / Horizon
        |
        | Keystone token + Idempotency-Key
        v
+---------------- Platform Core API ----------------+
| LaunchTemplate | AutoScalingGroup | Protection    |
| Preflight       | Operation/Task  | Recycle Bin   |
+--------+--------------+--------------------+-------+
         |              |                    |
         v              v                    v
   Policy/Quota     Durable Task DB      Event Outbox
   Placement       + Lease/Retry         (Track B/C)
   IP/Capacity            |
                         v
                 Reconciler / Workers
                   |      |       |
                   v      v       v
                 Nova  Neutron  Cinder
                   |      |       |
                   +------+-------+
                          |
                  Aodh / Gnocchi / Ceilometer
                    (scaling signal only)
```

구현 원칙은 다음과 같다.

- API 요청과 실제 OpenStack 변경을 분리하고 durable Operation으로 추적한다.
- 모든 mutation은 `Idempotency-Key`와 요청 fingerprint를 사용한다.
- worker는 desired state를 반복 조정하는 reconciler로 구현한다.
- OpenStack resource ID와 플랫폼 resource ID를 별도로 저장한다.
- 사용자 입력은 Region/VPC/Subnet 중심이며 raw Rack/AZ를 일반 입력으로 다시
  노출하지 않는다.
- DB commit과 외부 이벤트 발행 사이의 유실을 막기 위해 transactional outbox를
  사용한다.
- 오류 메시지는 사용자용 안정 코드와 운영자용 correlation ID를 분리한다.

## 4. 공통 Operation/Task API

### 4.1 리소스 모델

```yaml
Operation:
  id: uuid
  project_id: keystone-project-uuid
  region_id: seoul-ssu-1
  action: instance.create
  target_type: instance
  target_id: optional-platform-resource-uuid
  request_fingerprint: sha256
  idempotency_key: caller-supplied-key
  state: REQUESTED|VALIDATING|SCHEDULED|RUNNING|ROLLING_BACK|SUCCEEDED|FAILED|CANCELLED
  progress_percent: 0..100
  current_step: nova.server.create
  error:
    code: stable.machine.readable.code
    message: localized-safe-message
    retryable: true|false
    correlation_id: uuid
  steps: [OperationStep]
  created_at: timestamp
  updated_at: timestamp
  expires_at: timestamp|null

OperationStep:
  name: string
  sequence: integer
  state: PENDING|RUNNING|SUCCEEDED|FAILED|SKIPPED|COMPENSATED
  attempt: integer
  started_at: timestamp|null
  finished_at: timestamp|null
  provider_request_id: string|null
```

상태 전이는 서버에서만 수행한다. `FAILED`는 부분 성공 리소스와 보상 결과를
함께 기록한다. Cancel은 안전한 단계에서만 허용하고 이미 완료된 provider
작업을 취소한 것처럼 표시하지 않는다.

### 4.2 제안 API

```text
GET    /v1/operations?project_id=self&state=RUNNING
GET    /v1/operations/{operation_id}
POST   /v1/operations/{operation_id}/retry
POST   /v1/operations/{operation_id}/cancel
GET    /v1/operations/{operation_id}/events
```

모든 mutation API는 동기 성공 객체 대신 `202 Accepted`, Operation URL 및
correlation ID를 반환한다. 같은 프로젝트·같은 idempotency key·같은 request
fingerprint는 기존 Operation을 반환하고, 같은 key에 다른 payload가 오면
`409 IDEMPOTENCY_KEY_REUSED`를 반환한다.

### 4.3 처리 Flow

```text
Request -> authenticate/authorize -> idempotency lookup
        -> Operation(REQUESTED) + Outbox commit
        -> Worker lease -> VALIDATING -> preflight snapshot
        -> SCHEDULED -> provider API steps
        -> provider state polling/reconcile
        -> SUCCEEDED
          or failure -> compensation -> FAILED/ROLLING_BACK result
```

## 5. Preflight/Dry-run

Preflight는 실제 리소스를 만들지 않고 동일한 정책·해석 로직으로 실행 가능성을
판정한다. 결과는 시점 의존적이므로 승인 토큰의 유효기간을 짧게 두고 실제
실행 시 핵심 조건을 다시 검증한다.

### 5.1 제안 모델과 API

```yaml
PreflightResult:
  id: uuid
  request_fingerprint: sha256
  decision: PASS|WARN|FAIL
  resolved:
    region_id: seoul-ssu-1
    subnet_id: uuid
    availability_zone: internal-rack-result
    external_network_id: uuid|null
  checks:
    - name: nova.quota.vcpu
      result: PASS|WARN|FAIL|UNKNOWN
      code: string
      message: safe-message
      evidence_ref: opaque-reference
  approval_token: signed-short-lived-token|null
  expires_at: timestamp
```

```text
POST /v1/preflight/instances
POST /v1/preflight/launch-templates/{id}/versions/{version}/instances
POST /v1/preflight/auto-scaling-groups
POST /v1/preflight/deletions
```

필수 검사기는 Keystone/OPA 권한, Nova/Cinder/Neutron quota, image/flavor/boot
mode 호환성, Placement capacity, Subnet IP 가용량, SG/port 제한, volume type 및
스토리지 접근성, Region/Subnet 기반 Rack 결정, 의존 리소스 및 삭제 보호다.
검사 API 장애는 임의로 PASS 처리하지 않고 중요도에 따라 `UNKNOWN` 또는
`FAIL_CLOSED`로 반환한다.

### 5.2 Flow

```text
Form/CLI payload -> normalize -> policy -> quota -> placement/capacity
                 -> network/IP -> storage -> dependency checks
                 -> resolved plan + warnings + short-lived approval token
                 -> user confirms -> mutation revalidates -> Operation 생성
```

## 6. Launch Template

Launch Template는 배포 방법이 아니라 버전 관리되는 Compute desired-state다.
비밀 값은 평문으로 저장하지 않고 Barbican 등 외부 secret reference만 허용한다.

### 6.1 제안 모델

```yaml
LaunchTemplate:
  id: uuid
  project_id: uuid
  name: string
  description: string
  default_version: integer
  deletion_protected: boolean

LaunchTemplateVersion:
  template_id: uuid
  version: integer
  image_id: glance-uuid
  flavor_id: nova-flavor-id
  network:
    vpc_id: uuid
    subnet_id: uuid
    security_group_ids: [uuid]
  block_devices: []
  user_data_ref: barbican-or-approved-object-ref|null
  metadata: {}
  tags: {}
  server_group_policy: optional
  checksum: sha256
  created_by: keystone-user-id
  created_at: timestamp
```

버전은 생성 후 immutable이며 수정은 새 버전을 만든다. Auto Scaling Group은
항상 명시적 version 또는 resolved version snapshot을 저장해 default version
변경으로 실행 중 그룹이 예고 없이 바뀌지 않게 한다.

```text
POST   /v1/launch-templates
POST   /v1/launch-templates/{id}/versions
GET    /v1/launch-templates/{id}/versions
PUT    /v1/launch-templates/{id}/default-version
POST   /v1/launch-templates/{id}/versions/{version}/launch
DELETE /v1/launch-templates/{id}
```

## 7. Auto Scaling

### 7.1 제안 모델

```yaml
AutoScalingGroup:
  id: uuid
  project_id: uuid
  region_id: string
  launch_template:
    id: uuid
    version: integer
  min_size: integer
  desired_capacity: integer
  max_size: integer
  subnet_ids: [uuid]
  load_balancer_target_refs: []
  health_check: NOVA|LOAD_BALANCER|COMBINED
  cooldown_seconds: integer
  replacement_policy: rolling
  deletion_protected: boolean
  state: ACTIVE|SCALING|DEGRADED|DELETING|ERROR

ScalingPolicy:
  type: TARGET_TRACKING|STEP|SCHEDULED
  metric_ref: gnocchi-or-aodh-resource
  threshold/target: number
  adjustment: integer|null
  evaluation_periods: integer
```

### 7.2 Scaling Flow

```text
Ceilometer -> Gnocchi -> Aodh alarm transition
                         |
                         v signed/deduplicated event
                Scaling evaluator
                  -> cooldown/min/max check
                  -> Operation(scale-out/in)
                  -> preflight
                  -> Nova server + Neutron port + Cinder volumes
                  -> readiness/health check
                  -> LB member register/deregister (optional)
                  -> desired/actual convergence + history event
```

Scale-in은 임의 인스턴스를 즉시 삭제하지 않는다. unhealthy 우선, LB drain,
삭제 보호 및 local/attached data 정책, 가장 오래된/가장 새로운 인스턴스 정책을
명시하고 Operation으로 추적한다. Rack 분산은 사용자가 raw AZ를 고르는 방식이
아니라 선택된 Subnet과 플랫폼 placement 계약을 따른다.

## 8. Soft-delete, Recycle Bin 및 Deletion Protection

두 기능은 구분한다.

- **Deletion Protection**: 삭제 요청 자체를 `409 RESOURCE_PROTECTED`로 차단한다.
- **Soft-delete/Recycle Bin**: 보호가 꺼진 리소스를 즉시 purge하지 않고 복구
  가능한 상태와 만료시각으로 전환한다.

### 8.1 제안 모델/API

```yaml
ResourceProtection:
  resource_type: instance|launch_template|auto_scaling_group|...
  resource_id: uuid
  deletion_protected: boolean
  updated_by: keystone-user-id
  reason: string|null

RecycleBinEntry:
  id: uuid
  resource_type: string
  resource_id: uuid
  provider_resource_ids: {}
  deleted_by: keystone-user-id
  deleted_at: timestamp
  purge_after: timestamp
  restore_capability: FULL|REBUILD|METADATA_ONLY|NONE
  dependency_snapshot: {}
  state: RETAINED|RESTORING|RESTORED|PURGING|PURGED|ERROR
```

```text
PUT    /v1/resources/{type}/{id}/deletion-protection
DELETE /v1/resources/{type}/{id}             # protection/preflight 적용
GET    /v1/recycle-bin
POST   /v1/recycle-bin/{entry_id}/restore
DELETE /v1/recycle-bin/{entry_id}             # 명시적 purge, 강화 권한 필요
```

OpenStack 서비스마다 실제 복구 능력이 다르므로 UI에서 모두 `복원 가능`으로
표시하지 않는다. Nova native soft-delete를 사용할 수 있으면 adapter가 이를
활용하고, 지원하지 않는 리소스는 metadata snapshot/backup 기반 재구축 또는
`NONE`으로 명시한다. 연결 volume, FIP, port, DNS, LB membership의 보존 및 복원
정책은 리소스별로 별도 acceptance를 통과해야 한다.

### 8.2 삭제 Flow

```text
Delete -> protection check -> dependency preflight
       -> user impact/retention plan -> Operation
       -> detach/drain or native soft-delete
       -> RecycleBinEntry(RETAINED)
       -> restore before purge_after
          or retention controller -> purge Operation -> PURGED
```

## 9. 예상 구현 위치와 파일 소유권

정확한 디렉터리는 설계 검토 후 확정하되 다음 경계를 따른다.

| 영역 | Track A 예상 변경 위치 | 비고 |
|---|---|---|
| Core API/worker | 신규 `images/platform-core-orchestrator/` | API, DB migration, reconciler, adapters |
| 배포 | 신규 `deploy/values/features/core-orchestrator.yaml`, 관련 manifest/script | 다른 site values를 직접 재작성하지 않음 |
| Horizon | 신규 `images/horizon-core-orchestration-dashboard/` | 기존 dashboard overlay와 독립 유지 |
| Telemetry adapter | `components/aodh/`, `components/gnocchi/`, `components/ceilometer/`의 Track A 전용 파일 | 기존 차트 변경은 소유자 협의 후 |
| Provider adapters | `components/nova/` 및 필요한 Neutron/Cinder 신규 adapter 파일 | upstream vendored 코드를 직접 수정하지 않음 |
| 검증 | 신규 `deploy/tests/core-orchestrator/`, `deploy/scripts/verify-core-orchestrator.sh` | destructive test는 격리 프로젝트에서만 |
| 문서 | 이 파일 및 추후 Track A 전용 runbook | Track B/C 문서 수정 금지 |

병렬 작업 충돌 방지를 위한 **Track A 독점 파일 소유권**은 위 신규 디렉터리와
`core-orchestrator` 이름을 가진 신규 파일로 제한한다. 아래 공용 파일은 단독으로
수정하지 않고 통합 담당자가 최종 병합한다.

- `images/horizon-complete/Dockerfile`
- `deploy/scripts/build-images.sh`
- `deploy/scripts/reconcile-full-stack.sh`
- `deploy/values/site/*.yaml`
- `deploy/releases/*`, `deploy/locks/*`
- 공용 README와 문서 목차

Track A는 공용 파일에 필요한 변경을 `integration-requirements.md` 또는 PR 설명에
패치 단위로 기록하고, Track B/C 완료 후 통합 담당자가 반영한다.

## 10. 단계별 ToDo

### Phase A0 — Discovery와 계약 고정

- [ ] Nova/Cinder/Neutron API microversion과 native soft-delete/lock 기능을 조사한다.
- [ ] Heat/Senlin 설치·지원 상태를 확인하고 reuse 대 자체 구현 ADR을 작성한다.
- [ ] 기존 facade, Horizon, OPA, notification/telemetry 인터페이스를 inventory한다.
- [ ] 리소스별 quota, rollback, restore capability matrix를 작성한다.
- [ ] 상태 전이, 오류 코드, idempotency 및 retention ADR을 승인받는다.
- [ ] Region/Subnet 자동 placement 계약과 API 입력 스키마를 대조한다.
- [ ] DB HA, migration, backup, worker lease 요구사항을 확정한다.

### Phase A1 — Operation 기반

- [ ] Operation/Step/Outbox DB schema와 migration을 구현한다.
- [ ] Keystone project scope와 OPA authorization middleware를 구현한다.
- [ ] idempotency-key 저장, payload fingerprint 및 충돌 응답을 구현한다.
- [ ] worker lease, heartbeat, bounded retry, dead-letter 처리를 구현한다.
- [ ] 사용자 오류 코드와 correlation ID/log context를 구현한다.
- [ ] cancel/retry/compensation 상태 머신을 구현한다.
- [ ] list/detail/event API와 project isolation을 구현한다.
- [ ] Prometheus metric과 stuck-operation alert 입력을 제공한다.

### Phase A2 — Preflight

- [ ] 공통 검사기 interface와 PASS/WARN/FAIL/UNKNOWN 의미를 구현한다.
- [ ] policy/quota/image-flavor/placement/network/storage 검사기를 구현한다.
- [ ] Rack/AZ 자동 결정 결과를 설명 가능한 evidence로 반환한다.
- [ ] short-lived signed approval token과 실행 시 재검증을 구현한다.
- [ ] provider timeout/circuit breaker/cache 정책을 구현한다.
- [ ] Horizon 생성 화면에서 mutation 전 preflight 요약을 표시한다.

### Phase A3 — Launch Template

- [ ] template 및 immutable version API/DB를 구현한다.
- [ ] image, flavor, subnet, SG, block device reference 검증을 구현한다.
- [ ] secret 평문 금지와 approved secret reference 검증을 구현한다.
- [ ] default version 변경 및 explicit version launch를 구현한다.
- [ ] Nova/Neutron/Cinder 요청 compiler와 resource mapping을 구현한다.
- [ ] 단일 인스턴스 launch/rollback을 Operation으로 연결한다.
- [ ] Horizon 목록·버전 비교·생성·실행 UI를 구현한다.

### Phase A4 — Auto Scaling

- [ ] ASG, instance membership, scaling policy 모델을 구현한다.
- [ ] desired/min/max reconcile loop와 중복 event 억제를 구현한다.
- [ ] Aodh alarm webhook의 서명/인증/순서 역전/재전송 처리를 구현한다.
- [ ] target tracking, step, scheduled policy를 단계적으로 구현한다.
- [ ] scale-out preflight와 template version snapshot을 구현한다.
- [ ] health evaluation과 unhealthy replacement를 구현한다.
- [ ] LB drain/register adapter 인터페이스를 구현한다.
- [ ] cooldown, rate limit, oscillation 방지 및 scaling history를 구현한다.
- [ ] Subnet 기반 Rack 분산과 capacity 부족 fallback 규칙을 검증한다.
- [ ] Horizon ASG/instance/activity/policy UI를 구현한다.

### Phase A5 — Protection과 Recycle Bin

- [ ] 공통 deletion-protection API와 모든 Track A mutation guard를 구현한다.
- [ ] dependency graph 및 delete preflight를 구현한다.
- [ ] resource별 restore capability matrix를 코드로 강제한다.
- [ ] Nova native soft-delete adapter를 지원 여부에 따라 구현한다.
- [ ] retention controller와 privileged purge Operation을 구현한다.
- [ ] restore 시 ID/IP/volume/port 보존 가능 여부를 검증하고 표시한다.
- [ ] Horizon 보호 토글, 휴지통, 만료시각, 복원/purge UI를 구현한다.

### Phase A6 — 운영 전환

- [ ] API/worker HA, leader/lease 장애 및 DB failover를 시험한다.
- [ ] audit/event 소비자 없이도 core transaction이 안전함을 검증한다.
- [ ] canary project에서 shadow preflight를 실행해 오탐을 측정한다.
- [ ] feature flag로 template launch, ASG, recycle bin을 순서대로 활성화한다.
- [ ] rollback/disable 절차와 데이터 보존 runbook을 작성한다.
- [ ] SLO, 대시보드, 경보, 용량 계획을 승인받는다.

## 11. 테스트 및 인수 기준

### 11.1 공통 API

- 같은 idempotency key와 payload를 100회 재전송해 provider 리소스가 하나만
  생성된다.
- 같은 key에 다른 payload는 언제나 409로 거부된다.
- API/worker/DB/RabbitMQ 중 하나를 단계별로 재시작해도 Operation이 유실되거나
  이중 완료되지 않는다.
- 다른 프로젝트는 ID를 알아도 Operation, template, ASG, recycle entry를 조회할
  수 없다.
- 모든 실패 응답은 안정 오류 코드와 correlation ID를 제공하고 credential을
  노출하지 않는다.

### 11.2 Preflight/Launch Template

- quota 부족, IP 부족, image-flavor 부적합, placement 부족, 정책 거부를 실제
  mutation 전에 재현성 있게 차단한다.
- dry-run은 Nova/Neutron/Cinder 리소스를 만들지 않는다.
- 만료되거나 payload가 달라진 approval token은 실행에 사용되지 않는다.
- template version은 수정 불가하며 동일 버전 launch 결과의 입력이 동일하다.
- default version 변경은 이미 존재하는 ASG의 pinned version을 변경하지 않는다.

### 11.3 Auto Scaling

- 동일 Aodh event의 재전송이 중복 scale-out을 만들지 않는다.
- min/max, cooldown, rate limit을 모든 동시 요청에서 지킨다.
- scale-out된 서버가 정상 상태가 된 뒤에만 LB ready member로 전환된다.
- scale-in은 drain 완료 또는 명시적 timeout 정책 후 진행된다.
- worker 장애 중 생성된 부분 리소스가 reconcile/compensation으로 수렴한다.
- 사용자는 Region/Subnet만 선택하며 실제 인스턴스가 placement 계약에 맞게
  Rack에 배치된다.

### 11.4 보호·삭제·복원

- 보호된 리소스는 UI, API, ASG scale-in 및 cascade delete 어디서도 삭제되지
  않는다.
- 보존기간 전에는 권한 있는 사용자가 지원 수준에 맞게 복원할 수 있다.
- 보존기간 후 purge는 한 번만 실행되며 의존 리소스 누수를 남기지 않는다.
- 복원이 불가능한 리소스는 사전에 `NONE`으로 표시되고 거짓 성공을 반환하지
  않는다.
- 프로젝트 간 restore/purge 및 보호 변경이 정책으로 차단된다.

### 11.5 운영 인수

- 최소 3개 API replica와 다중 worker 환경에서 rolling update 중 요청이
  지속된다.
- stuck, retry 폭증, reconciliation drift, scaling oscillation, purge 실패 metric이
  제공된다.
- 24시간 canary와 장애 주입 시험 후 orphan provider resource가 0개다.
- feature flag off 및 이전 이미지 rollback 절차가 검증된다.

## 12. Track B/C와의 인터페이스

Track A는 다른 트랙 구현을 기다리지 않고 core 기능을 개발하되 다음 계약을
먼저 고정한다.

### Track B에 제공할 인터페이스

- Transactional outbox의 `operation.*`, `resource.protection.*`,
  `recycle-bin.*`, `autoscaling.*` versioned event
- 사용자에게 보여줄 안정 오류 코드, 진행률, 대상 resource reference
- 알림 실패가 Operation 성공/실패 transaction을 되돌리지 않는 at-least-once
  소비 계약
- 비용·사용량 계층이 사용할 instance membership 및 lifecycle timestamp

### Track B에서 받을 인터페이스

- 알림 subscription/delivery API의 식별자와 delivery 상태 link
- 백업 또는 DR이 삭제/scale-in을 보류해야 할 때 사용할 비동기 hold 계약
- 비용 예측 결과는 preflight의 optional warning으로만 사용하며 core availability
  판단과 분리

### Track C에 제공할 인터페이스

- 모든 Operation과 보호 변경의 append-only audit event
- preflight check 결과와 policy decision reference
- 네트워크/이미지 진단기가 추가 check를 등록할 수 있는 versioned checker SPI
- template와 ASG가 참조한 image ID/version 및 immutable checksum

### Track C에서 받을 인터페이스

- OPA decision ID와 사용자용 거부 사유
- 네트워크 path diagnosis의 PASS/WARN/FAIL/UNKNOWN 결과
- 이미지 공급망의 trust/deprecation 판정
- 공통 tag validator/normalizer 결과

공유 schema는 JSON Schema/OpenAPI로 버전 관리한다. 소비자가 일시 중단돼도
Track A mutation은 outbox에 남아야 하며, 소비자 장애를 이유로 provider 작업을
중복 실행하지 않는다.

## 13. 명시적 제외 사항

Track A에서는 다음을 구현하지 않는다.

- 이메일, Webhook 등 알림 전달 채널과 구독 UI
- CloudKitty 기반 비용 산정과 예산 정책
- 백업 스케줄, DR failover/failback 오케스트레이션
- 인증서 발급/갱신 및 Secret rotation
- 통합 감사 검색 저장소와 검색 UI
- 패킷 probe, OVN path 분석기 및 네트워크 topology 구현
- Glance 이미지 빌드, 서명, SBOM, 취약점 검사 및 폐기 파이프라인
- 플랫폼 전체 공통 tag 정책 엔진
- Managed Database, Bare Metal 임대, Magnum 지속 운영 자동화
- Heat/Senlin을 검증 없이 설치하거나 기존 서비스 설정을 즉시 변경하는 작업
- production에서 검증 없이 destructive recycle/purge 시험을 수행하는 작업

이 제외 항목에 필요한 데이터는 versioned event/checker interface로만 연결하고,
해당 트랙의 파일을 Track A 변경에 포함하지 않는다.
