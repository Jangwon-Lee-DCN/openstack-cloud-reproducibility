# Track C ToDo — 복원력 및 플랫폼 운영 자동화

> 상태: 구현 전 작업 계약(초안)  
> 범위: P1 복원력 및 플랫폼 운영 기능  
> 병렬 트랙: Track A(Operation/Task), Track B(알림/감사)와 동시에 진행  
> 이 문서는 구현 완료를 선언하지 않는다. 체크된 항목과 검증 증거가 없는 기능은 제공 중으로 간주하지 않는다.

## 1. 목적

이 트랙은 이미 존재하는 OpenStack 백업, 스냅샷, 네트워크 조회, 이미지 업로드 같은 개별 API를 사용자가 신뢰할 수 있는 **정책 기반 운영 서비스**로 묶는다. 목표는 다음 다섯 가지다.

1. 정책에 따라 백업하고 실제 복구 가능성을 주기적으로 증명한다.
2. Rack 장애 시 서비스 단위로 failover/failback을 실행하고 RPO/RTO를 측정한다.
3. 사용자가 자신의 권한 범위 안에서 종단 간 네트워크 진단을 실행한다.
4. Compute 유지보수의 영향, 이동, 실패와 복구 상태를 사용자에게 제공한다.
5. 공식 이미지를 빌드부터 폐기까지 서명·검사·승격 가능한 공급망으로 관리한다.

## 2. 범위와 완료 정의

| Workstream | 이 트랙의 산출물 | 완료 조건 |
| --- | --- | --- |
| C1 정책 기반 백업 | 정책, 실행, 보존, 복구 검증 | 예약 실행뿐 아니라 격리된 restore drill이 성공하고 증거가 남음 |
| C2 DR 오케스트레이션 | 보호 그룹, DR 계획, failover/failback | Rack 장애 훈련에서 선언한 RPO/RTO를 측정하고 결과를 조회 가능 |
| C3 사용자 네트워크 진단 | 진단 요청, 정책 경로 분석, 제한된 probe | 예상 경로와 실제 probe 결과가 동일 작업 ID로 연결됨 |
| C4 인스턴스 유지보수 | 캠페인, 영향 분석, migration/evacuation | 사전 점검부터 종료 보고까지 재시작 가능한 상태 머신으로 동작 |
| C5 공식 이미지 공급망 | build, scan, sign, promote, deprecate | 검증되지 않은 이미지는 공식 카탈로그로 승격될 수 없음 |

공통 완료 조건:

- 모든 장기 작업은 Track A의 `Operation` API를 사용한다.
- 사용자 통지와 감사 이벤트는 Track B 계약을 사용한다.
- 프로젝트 경계, Keystone RBAC 및 OPA 정책을 우회하는 운영자 전용 API가 없어야 한다.
- API/CRD/DB 상태와 실제 OpenStack 리소스의 drift를 재조정할 수 있어야 한다.
- 정상 경로뿐 아니라 실패 주입 훈련 결과를 CI 또는 운영 검증 기록으로 보존한다.

## 3. 전체 토폴로지

```text
 User / Operator / Scheduler
              |
              v
 Horizon panels / Resilience API
              |
       Keystone + OPA
              |
              v
 Track A Operation/Task service <--------> Track B Notification/Audit
              |
       +------+------+---------------+----------------+
       |             |               |                |
       v             v               v                v
 Backup/Restore   DR Orchestrator  Network Probe   Maintenance
 Controller       Controller       Controller      Controller
       |             |               |                |
       |             |               |          Nova/Masakari/Placement
       |             |               |                |
 Cinder/Glance   Nova/Cinder     Neutron/OVN      Compute hosts
 Manila/RGW      Octavia/Designate  + probe agents
       |
       +---------------------> protected storage / recovery target

 Image Pipeline
 Git manifest -> Builder -> Scan/SBOM -> Sign -> Test boot -> Glance staging
                                                     |
                                                     v
                                    Approval/Policy -> official catalog
```

### 공통 제어 흐름

```text
Request
  -> authenticate/authorize
  -> validate + dry-run
  -> create Operation
  -> acquire idempotency/target lock
  -> execute child Tasks
  -> observe actual OpenStack state
  -> compensate or resume on failure
  -> emit audit event and user notification
  -> retain immutable evidence
```

Controller는 요청 HTTP 연결 안에서 장기 작업을 완료하지 않는다. 재시작 이후에도 `Operation`과 외부 리소스 ID를 기준으로 이어서 수행해야 한다.

## 4. 공통 리소스 및 API 계약

아래 이름은 Track C에서 필요한 논리 모델이다. Track A가 최종 URI와 스키마를 소유하므로 Track C 구현에서 별도 작업 모델을 만들지 않는다.

### 4.1 공통 참조 모델

```yaml
operationRef:
  id: op-uuid
  kind: backup-run|restore-drill|dr-failover|network-diagnostic|maintenance|image-build
  project_id: keystone-project-uuid
  requested_by: keystone-user-or-application-credential
  idempotency_key: client-generated-key
  correlation_id: trace-id
  state: requested|validating|running|waiting|rolling_back|succeeded|failed|cancelled
```

공통 요구사항:

- 생성 API는 `Idempotency-Key`를 받아 동일 요청의 중복 리소스 생성을 막는다.
- 사용자 응답에는 비밀, BMC 주소, 관리망 주소, 다른 프로젝트 UUID를 노출하지 않는다.
- 목록/상세 API는 `project_id`로 강제 범위 제한한다.
- 외부 OpenStack 리소스에는 가능한 경우 `operation_id`, 정책 ID 및 보호 그룹 ID를 tag/metadata로 기록한다.
- 삭제 API는 실행 중 작업과 증거 보존 기간을 확인한 뒤 처리한다.

### 4.2 Track C API namespace 제안

```text
/v1/backup-policies
/v1/backup-runs
/v1/restore-drills
/v1/protection-groups
/v1/dr-plans
/v1/dr-executions
/v1/network-diagnostics
/v1/maintenance-campaigns
/v1/image-products
/v1/image-builds
```

API는 제안이며 Track A의 API 규약 확정 후 URI를 동결한다. Horizon은 서비스별 OpenStack API를 직접 조합하지 않고 이 API와 `Operation` 상태를 조회한다.

## 5. C1 — 정책 기반 백업과 복구 검증

### 5.1 토폴로지와 흐름

```text
BackupPolicy + Scheduler
          |
          v
 Backup Controller ---> Track A Operation
    |        |  \
    |        |   +--> Glance image/snapshot
    |        +------> Cinder volume backup/snapshot
    +---------------> Manila snapshot / RGW export manifest
          |
          v
 Retention reconciler ---> expire only unprotected generations
          |
          v
 Restore Drill ---> isolated network/project ---> boot/mount/check ---> destroy
```

사용 흐름:

1. 사용자가 보호 대상, 일정, 보존 기간, 일관성 수준을 포함한 정책을 만든다.
2. Controller가 quota, 대상 상태, 백업 backend와 복구 목표를 사전 검증한다.
3. Scheduler가 실행을 만들고 Track A가 단계별 Task를 기록한다.
4. 애플리케이션 일관성이 요구되면 guest agent hook 또는 명시적 freeze/thaw를 수행한다.
5. 백업 완료 후 checksum, 원본 generation, 외부 객체 ID를 증거로 고정한다.
6. 보존 정책은 hold가 없는 오래된 generation만 제거한다.
7. 주기적인 restore drill이 격리된 대상에 복원하고 부팅·파일시스템·서비스 probe를 검증한다.

### 5.2 리소스 모델

```yaml
BackupPolicy:
  id: uuid
  project_id: uuid
  targets:
    - type: instance|volume|share|image|object-prefix
      id: openstack-resource-id
  schedule: cron-with-timezone
  consistency: crash|filesystem|application
  retention:
    keep_last: 7
    daily: 14
    weekly: 8
    legal_hold: false
  recovery_target: local|external-tier
  restore_drill:
    enabled: true
    interval_days: 30
    validation_profile: boot-and-health|mount-and-checksum|object-sample
  enabled: true

BackupRun:
  id: uuid
  policy_id: uuid
  operation_id: uuid
  source_generation: string
  artifacts: [{service, resource_id, checksum, size_bytes}]
  consistency_evidence: object
  started_at: timestamp
  completed_at: timestamp

RestoreDrill:
  id: uuid
  backup_run_id: uuid
  operation_id: uuid
  isolated_target: object
  probes: [{name, result, evidence_ref}]
  cleanup_state: pending|complete|failed
```

### 5.3 구현 체크리스트

- [ ] 정책 CRUD와 프로젝트별 RBAC를 정의한다.
- [ ] timezone을 포함한 schedule 파서와 missed-run 정책을 구현한다.
- [ ] Cinder backup/snapshot, Glance, Manila, RGW adapter의 capability discovery를 구현한다.
- [ ] instance-volume 관계와 boot-from-volume을 일관된 generation으로 고정한다.
- [ ] freeze 실패 시 `application`을 `crash`로 조용히 낮추지 않고 실행을 실패시킨다.
- [ ] 정책 수정 중 실행 중인 generation의 immutable snapshot을 보존한다.
- [ ] backend 객체와 `BackupRun` 사이 drift detector를 구현한다.
- [ ] retention 계산에 legal hold, 최근 성공본, 진행 중 restore 참조를 반영한다.
- [ ] 격리 프로젝트/네트워크를 쓰는 restore drill executor를 구현한다.
- [ ] drill 종료 시 임시 VM, port, volume, secret을 확실히 정리한다.
- [ ] 복원 가능한 크기, 예상 시간, quota 부족을 dry-run에서 표시한다.
- [ ] Horizon에 정책, 실행 이력, 마지막 성공 복구 시각을 표시한다.

### 5.4 시험과 인수 기준

- 정책에 따라 3회 연속 실행되고 중복 scheduler tick에도 실행은 한 번만 생성된다.
- boot volume과 data volume을 같은 recovery point로 복원해 파일 checksum이 일치한다.
- Controller 재시작 후 작업이 새 백업을 중복 생성하지 않고 이어진다.
- retention은 legal hold 및 마지막 성공 복구본을 삭제하지 않는다.
- restore drill 실패가 원본 서비스에 영향을 주지 않고 임시 자원이 정리된다.
- 프로젝트 A는 프로젝트 B의 정책, artifact ID, restore 결과를 볼 수 없다.

실패 훈련:

- [ ] 백업 중 controller kill
- [ ] Cinder/RGW 일시 중단과 재시도 한도 초과
- [ ] 백업 객체 checksum 불일치
- [ ] restore 중 quota 고갈
- [ ] freeze 성공 후 backup 실패 시 thaw 보상 동작
- [ ] retention 실행과 restore 실행의 경합

## 6. C2 — DR 오케스트레이션

### 6.1 토폴로지와 흐름

```text
ProtectionGroup
  VM + volumes + ports + FIP + LB + DNS
                  |
                  v
               DR Plan
  detect/declare -> fence source -> restore/recreate -> reconnect
       -> health check -> switch LB/DNS -> observe -> complete
                  |
                  v
              Failback Plan
  validate source -> reverse sync -> controlled switchover -> verify
```

Rack 장애 감지는 자동 실행의 충분조건이 아니다. 초기 운영에서는 탐지 후 운영자 승인을 기본값으로 하고, 검증된 protection class만 자동 failover를 허용한다. split-brain 방지를 위해 source fencing이 증명되지 않으면 writable storage를 target에 연결하지 않는다.

### 6.2 리소스 모델

```yaml
ProtectionGroup:
  id: uuid
  project_id: uuid
  members: [{type, id, dependency_order}]
  recovery_class: bronze|silver|gold
  desired_rpo_seconds: 3600
  desired_rto_seconds: 1800

DRPlan:
  id: uuid
  protection_group_id: uuid
  source_failure_domain: rack-1
  target_policy: auto-select-healthy-rack
  steps:
    - validate
    - fence-source
    - recover-storage
    - recreate-compute
    - restore-network
    - attach-lb
    - switch-dns
    - health-check
  approval_policy: manual|automatic
  rollback_boundary: step-name

DRExecution:
  id: uuid
  plan_id: uuid
  operation_id: uuid
  mode: drill|failover|failback
  recovery_point: timestamp
  measured_rpo_seconds: integer
  measured_rto_seconds: integer
  fencing_evidence_ref: string
```

### 6.3 구현 체크리스트

- [ ] dependency graph를 VM, volume, port, FIP, LB, DNS까지 수집한다.
- [ ] 순환 의존성과 보호 불가능한 외부 의존성을 dry-run에서 차단한다.
- [ ] rack/failure-domain 상태 및 target capacity preflight를 구현한다.
- [ ] source fencing adapter와 증거 형식을 정의한다.
- [ ] 복구 순서와 재시도/보상 가능한 경계를 명시한다.
- [ ] FIP, Octavia VIP, Designate record의 전환 방식을 리소스별로 구현한다.
- [ ] 기존 ID 유지가 불가능한 리소스의 old-to-new mapping을 보존한다.
- [ ] drill 모드는 운영 DNS/FIP를 변경하지 않는 격리 경로를 사용한다.
- [ ] failback은 별도 승인과 reverse-sync 검증을 요구한다.
- [ ] 실제 측정 RPO/RTO와 목표 위반 사유를 결과에 기록한다.
- [ ] Rack 장애 이외의 단일 VM/host 장애는 DR이 아닌 Nova/Masakari 경로로 분리한다.
- [ ] Horizon에 보호 범위, 마지막 drill, failover 준비 상태를 표시한다.

### 6.4 시험과 인수 기준

- 보호 그룹 dry-run이 필요한 target vCPU/RAM/storage/IP 용량을 계산한다.
- 격리 DR drill에서 복구된 애플리케이션 health check가 통과한다.
- source fencing 실패 시 writable target 활성화 전에 중단된다.
- 동일 실행 요청을 반복해도 DNS/FIP/LB 전환이 중복되지 않는다.
- 부분 실패 후 재시작하면 마지막 확인된 단계부터 계속된다.
- 측정된 RPO/RTO가 타임라인과 함께 사용자 및 감사 화면에 남는다.

실패 훈련:

- [ ] Rack 네트워크 완전 단절
- [ ] source가 늦게 복귀하는 split-brain 시나리오
- [ ] target Rack capacity 부족
- [ ] storage 복구 성공 후 VM 생성 실패
- [ ] LB 전환 성공 후 DNS 전환 실패
- [ ] failover 도중 controller leader 변경
- [ ] failback reverse-sync checksum 불일치

## 7. C3 — 사용자 네트워크 진단 실행

### 7.1 토폴로지와 흐름

```text
User source/destination selection
              |
              v
 Diagnostic API -> Keystone/OPA -> redact/authorize
              |
        +-----+------------------+
        |                        |
        v                        v
 Declarative analyzer        Probe executor
 Neutron + OVN NB/SB         tenant VM/namespace or
 routes/SG/NACL/NAT/LB        controlled edge agents
        |                        |
        +-----------+------------+
                    v
       hop decisions + probe evidence + mismatch
```

분석기는 논리적으로 허용되는지를 설명하고, probe는 실제 도달성을 제한적으로 검증한다. 둘 중 하나만으로 성공을 단정하지 않는다. OVN NB/SB 원본 UUID, chassis 및 관리 주소는 운영자 증거로만 저장하고 사용자에게는 논리 리소스 이름과 차단 사유로 변환한다.

### 7.2 리소스 모델

```yaml
NetworkDiagnostic:
  id: uuid
  project_id: uuid
  operation_id: uuid
  source:
    type: instance|port|load-balancer|external-client
    id: resource-id
  destination:
    address: ip-or-fqdn
    port: 443
    protocol: tcp|udp|icmp|dns|http|https
  mode: analyze|probe|both
  limits:
    timeout_seconds: 10
    packet_count: 3
  result:
    verdict: reachable|blocked|indeterminate|mismatch
    hops: []
    policy_decisions: []
    probe_summary: object
```

### 7.3 구현 체크리스트

- [ ] source 리소스 소유권 및 destination 허용 정책을 검증한다.
- [ ] SG, NACL, subnet route, router route/policy, SNAT/DNAT/FIP, LB 경로 adapter를 구현한다.
- [ ] OVN NB desired state와 SB binding/chassis state를 상관 분석한다.
- [ ] DNS 진단은 응답 IP와 이후 L3/L4 진단을 연결한다.
- [ ] probe 실행 위치를 source와 동일한 논리 경로에 배치한다.
- [ ] arbitrary payload, port scan, spoofed source 및 지속 probe를 차단한다.
- [ ] 프로젝트별 rate limit, 동시 실행 수 및 TTL을 적용한다.
- [ ] `blocked`와 관측 불충분인 `indeterminate`를 구분한다.
- [ ] 선언상 허용/실제 실패 등 mismatch를 운영 경보 후보로 표시한다.
- [ ] Horizon topology에서 hop을 선택하면 해당 정책 판정 근거를 표시한다.
- [ ] 민감한 infrastructure hop은 역할에 따라 redact한다.

### 7.4 시험과 인수 기준

- SG deny, NACL deny, route 없음, FIP 미연결, LB unhealthy를 각각 정확히 구분한다.
- 프로젝트 간 요청은 다른 tenant의 topology를 노출하지 않고 거부된다.
- IPv4, DNS, TCP/UDP/ICMP의 지원 범위가 API capability로 조회된다.
- probe pod/agent가 timeout 후 남지 않고 network namespace가 정리된다.
- NB는 허용하지만 SB port binding이 없는 경우 `mismatch`로 판정한다.
- 결과에서 사용자가 수정할 수 있는 리소스와 운영자 조치가 필요한 지점을 구분한다.

실패 훈련:

- [ ] OVN NB 또는 SB 조회 불가
- [ ] probe agent 비정상 종료
- [ ] 분석 도중 port가 다른 chassis로 이동
- [ ] DNS가 여러 IP를 반환하고 일부만 실패
- [ ] rate-limit 우회 및 cross-project UUID 입력
- [ ] 결과 저장 전 Controller 재시작

## 8. C4 — 인스턴스 유지보수 경험

### 8.1 토폴로지와 흐름

```text
Operator creates MaintenanceCampaign
                 |
                 v
 Impact analyzer: host -> instances -> volumes/network/LB/SLA
                 |
       notify + approval window
                 |
                 v
 disable scheduling -> live/cold migrate or evacuate -> verify
                 |
        host maintenance / reboot
                 |
 re-enable -> rebalance policy check -> completion report
```

정상 계획 정비는 Nova host maintenance와 migration을 사용하고, 비계획 장애는 Masakari/evacuation 경로를 사용한다. 같은 인스턴스에 두 경로가 동시에 실행되지 않도록 instance operation lock을 공유한다.

### 8.2 리소스 모델

```yaml
MaintenanceCampaign:
  id: uuid
  operation_id: uuid
  failure_domain: rack-1|host-uuid
  reason: string
  window: {start, end, timezone}
  strategy: live-migrate|cold-migrate|evacuate|mixed
  max_unavailable: 1
  approval_policy: operator|project-owner
  affected_instances:
    - instance_id: uuid
      eligibility: eligible|blocked|manual
      reason_codes: []
      selected_target: host-or-rack
      task_state: string
  rollback_policy: object
```

### 8.3 구현 체크리스트

- [ ] host aggregate, trait, AZ/rack, PCI/GPU, NUMA, hugepage, local disk 제약을 영향 분석에 포함한다.
- [ ] target capacity와 anti-affinity/server-group 충족 여부를 사전 검증한다.
- [ ] live migration 불가 사유와 cold/evacuation 대안을 사용자 언어로 변환한다.
- [ ] scheduler disable과 기존 disable reason 보존을 구현한다.
- [ ] 캠페인별 `max_unavailable` 및 Rack 분산 불변조건을 강제한다.
- [ ] volume attachment, port binding, FIP, LB member health를 migration 후 검증한다.
- [ ] 장기 실행 VM의 console/log 보존과 사용자 영향 시간을 기록한다.
- [ ] 캠페인 취소 시 이미 이동한 VM을 무조건 원복하지 않고 명시된 정책을 따른다.
- [ ] host 복귀 전에 compute service와 dataplane health gate를 통과시킨다.
- [ ] 사용자에게 예정, 시작, 지연, 완료, 실패 상태를 제공한다.
- [ ] 운영자에게 block된 VM과 수동 조치 runbook을 제공한다.

### 8.4 시험과 인수 기준

- 일반 shared-storage VM은 무중단 live migration 후 네트워크 세션 검증을 통과한다.
- GPU/PCI passthrough, NUMA pinning, local disk VM은 잘못된 live migration을 시도하지 않는다.
- 캠페인 중 controller 재시작 후 중복 migration 없이 상태를 복원한다.
- `max_unavailable`과 server-group anti-affinity가 모든 단계에서 유지된다.
- 실패한 VM 때문에 성공한 VM의 결과가 사라지지 않고 부분 완료로 보고된다.
- host enable 전에 Nova, libvirt, OVN chassis 및 storage 연결 검사가 통과한다.

실패 훈련:

- [ ] migration 중 source compute 전원 손실
- [ ] target compute 용량 급변
- [ ] port binding은 이동했으나 dataplane 연결 실패
- [ ] volume reattach 지연
- [ ] host가 정비 창 이후에도 복귀하지 않음
- [ ] Masakari evacuation과 계획 migration 동시 요청

## 9. C5 — 공식 이미지 공급망 자동화

### 9.1 토폴로지와 흐름

```text
Signed image manifest in Git
          |
          v
 Ephemeral builder -> hardening -> package updates
          |
          v
 SBOM + vulnerability/malware scan + checksum
          |
          v
 artifact signing / provenance attestation
          |
          v
 Glance staging (not official)
          |
 test boot -> cloud-init -> network/storage/agent checks
          |
 policy/approval gate
          |
          v
 Glance official metadata + Horizon Platform Images
          |
 observe adoption -> deprecate -> disable -> retain/delete
```

공식 여부는 Glance `visibility=public`만으로 판정하지 않는다. 플랫폼 발행자와 검증된 property/서명을 모두 만족해야 한다. 일반 사용자의 public/community/shared 이미지는 공식 이미지로 승격되지 않는다.

### 9.2 리소스 모델과 Glance metadata

```yaml
ImageProduct:
  id: ubuntu-24.04
  channel: stable|candidate|deprecated
  architecture: x86_64
  support_until: date
  owner_project_id: platform-image-project
  replacement_product_id: optional

ImageBuild:
  id: uuid
  operation_id: uuid
  product_id: ubuntu-24.04
  source_digest: sha256
  artifact_digest: sha256
  sbom_ref: immutable-uri
  provenance_ref: immutable-uri
  signature_ref: immutable-uri
  scan_summary: object
  test_results: []
  promotion_state: built|quarantined|candidate|official|deprecated|revoked
```

필수 Glance property 제안:

```text
dcn_image_class=platform
dcn_image_product=<stable product id>
dcn_image_build=<build uuid>
dcn_image_channel=stable|candidate|deprecated
dcn_source_digest=sha256:...
dcn_artifact_digest=sha256:...
dcn_signature_ref=<immutable reference>
dcn_sbom_ref=<immutable reference>
dcn_support_until=YYYY-MM-DD
dcn_replacement_image_id=<optional glance uuid>
```

### 9.3 구현 체크리스트

- [ ] 소스 manifest, 패키지 pin, builder image를 Git으로 버전 관리한다.
- [ ] build worker는 단기 credential과 격리된 network/project를 사용한다.
- [ ] artifact checksum, SBOM, provenance 및 서명을 immutable store에 보존한다.
- [ ] severity/예외 만료일 기반 취약점 promotion policy를 구현한다.
- [ ] staging Glance image는 일반 프로젝트가 launch하지 못하도록 격리한다.
- [ ] cloud-init, SSH key, metadata, config-drive, volume boot, network agent 시험을 자동화한다.
- [ ] UEFI/BIOS, q35, architecture 등 지원 조합을 capability matrix로 관리한다.
- [ ] promotion은 플랫폼 owner와 `dcn_image_class=platform`을 함께 강제한다.
- [ ] Horizon Platform Images 분류가 위 계약을 사용하도록 통합 시험한다.
- [ ] 사용 중인 서버와 Launch Template 참조 수를 deprecation 전에 계산한다.
- [ ] deprecate/disable/revoke 단계를 구분하고 replacement를 제공한다.
- [ ] 심각한 공급망 사고의 긴급 revoke와 영향 리소스 조회를 구현한다.
- [ ] 서명키 rotation과 과거 이미지 검증 정책을 정의한다.

### 9.4 시험과 인수 기준

- 동일 manifest의 재빌드 provenance가 남고 차이 원인을 비교할 수 있다.
- 서명 누락, digest 불일치 또는 정책 초과 CVE가 있으면 promotion이 차단된다.
- 공식 owner가 아닌 사용자가 `dcn_image_class=platform`을 설정해도 공식 목록에 나타나지 않는다.
- 공식 이미지로 boot한 VM에서 cloud-init, DHCP, metadata, block storage가 동작한다.
- deprecated 이미지는 기존 VM을 중단하지 않지만 신규 선택 시 replacement 경고를 제공한다.
- revoked 이미지는 정책에 따라 신규 boot가 거부되고 영향 프로젝트에 통지된다.

실패 훈련:

- [ ] builder 또는 scanner compromise 가정과 credential 폐기
- [ ] signature verification 실패
- [ ] SBOM/provenance 저장소 일시 중단
- [ ] staging test 중 cloud-init timeout
- [ ] promotion 직후 치명적 CVE 발견
- [ ] 서명키 rotation 중 이전 이미지 검증

## 10. Track A/B 의존 계약

### Track A — Operation/Task 및 dry-run

Track A가 소유하고 Track C가 소비한다.

- `Operation`, `Task`, idempotency, cancellation, retry, compensation 상태 모델
- 단계별 progress와 사용자용/운영자용 오류 분리
- target lock 및 동일 리소스 동시 작업 충돌 응답
- dry-run 결과의 공통 warning/error/capacity schema
- correlation/trace ID와 장기 작업 retention
- Horizon 공통 작업 상세/타임라인 component

Track A가 확정되기 전 Track C는 adapter 내부 상태를 만들 수 있지만 외부 공개 API로 고정하지 않는다. Track C 고유 리소스는 `operation_id`만 참조하며 Task 상태를 복제 저장하지 않는다.

### Track B — 알림 및 감사

Track B가 소유하고 Track C가 소비한다.

- 사용자/프로젝트 구독, email/webhook 전달, 중복 억제
- 표준 event envelope, severity, deduplication key
- actor, project, action, target, before/after, decision, correlation ID 감사 스키마
- delivery 실패 재시도와 dead-letter 처리
- 감사 기록 보존·검색·내보내기

Track C가 발행할 최소 이벤트:

```text
backup.run.{started,succeeded,failed}
restore.drill.{succeeded,failed,cleanup_failed}
dr.execution.{approval_required,started,rpo_breached,rto_breached,succeeded,failed}
network.diagnostic.{started,blocked,mismatch,failed}
maintenance.{scheduled,started,delayed,instance_failed,completed}
image.build.{quarantined,promotion_required,promoted,deprecated,revoked}
```

Track C는 SMTP/Slack/Webhook client 또는 별도 감사 DB를 구현하지 않는다.

## 11. 병렬 개발 파일 소유권과 충돌 방지

이 문서가 제안하는 초기 ownership은 구현 시작 전에 세 트랙이 확정해야 한다.

| 소유자 | 독점 수정 경로(제안) | 다른 트랙의 접근 방식 |
| --- | --- | --- |
| Track C | `services/resilience/**`, `controllers/backup/**`, `controllers/dr/**`, `controllers/network-diagnostic/**`, `controllers/maintenance/**`, `pipelines/official-images/**`, Track C 전용 Horizon panel/adapter | 코드 변경은 Track C PR을 통해 수행 |
| Track A | `services/operations/**`, 공통 task SDK, 공통 dry-run/error UI | Track C는 versioned client/contract만 소비 |
| Track B | `services/notifications/**`, `services/audit/**`, receiver와 공통 event SDK | Track C는 event producer interface만 소비 |
| 배포 통합 담당 | 공용 Helm umbrella, release lock, site values, 공통 RBAC/CRD bundle | 각 트랙은 overlay 조각을 제공하고 최종 통합은 순차 수행 |

충돌 방지 규칙:

- [ ] 각 트랙은 자기 ToDo 문서 외의 공용 문서 index를 동시에 수정하지 않는다.
- [ ] OpenAPI 공통 component는 Track A가 먼저 version을 만들고 Track C는 `$ref`한다.
- [ ] event schema는 Track B가 먼저 version을 만들고 Track C는 fixture로 검증한다.
- [ ] Horizon 공통 navigation 변경은 통합 담당이 수행하고 Track C는 독립 panel registration만 제공한다.
- [ ] 공용 chart/values/release lock은 기능 브랜치에서 직접 동시에 수정하지 않는다.
- [ ] DB migration prefix 또는 revision range를 트랙별로 예약한다.
- [ ] 통합 전 contract test를 consumer/provider 양쪽 CI에서 실행한다.

## 12. 명시적 제외 범위

다음은 Track C가 구현하지 않는다.

- Track A 자체: 공통 Operation 엔진, 범용 dry-run, 공통 오류/작업 UI
- Track B 자체: 알림 채널, 구독 관리, 감사 검색 저장소
- 비용·사용량·예산, 공통 Tag 정책, Secret rotation, 인증서 자동화
- Launch Template, 일반 VM Auto Scaling, managed database
- Magnum 지속 운영, Bare Metal 임대, Spot/Capacity Reservation
- 새로운 backup storage hardware 도입 또는 기존 Ceph/PowerStore 물리 재설계
- OVN dataplane 기능 개발; C3는 기존 Neutron/OVN 상태를 읽고 제한된 probe만 수행
- Masakari monitor의 무검증 활성화 또는 fencing 없는 자동 DR
- 사용자 이미지 자동 승격; 공식 이미지 공급망은 플랫폼 발행 이미지에만 적용
- 운영 배포, production 데이터 삭제, 실제 failover 수행; 별도 승인된 구현/훈련 단계에서 실행

## 13. 단계별 실행 순서

### Phase C0 — 계약과 안전장치

- [ ] Track A/B versioned contract 확정
- [ ] 프로젝트 RBAC/OPA action matrix 확정
- [ ] 리소스 UUID, tag, metadata, evidence retention 표준 확정
- [ ] 외부 서비스 capability inventory와 sandbox fixture 작성
- [ ] production과 격리된 failure-drill 환경 정의

### Phase C1 — Read-only와 dry-run

- [ ] 백업 가능성/복구 예상 용량 분석
- [ ] DR dependency graph와 target capacity 분석
- [ ] network analyze-only 결과
- [ ] maintenance impact 분석
- [ ] 이미지 manifest/scan/sign 검증

이 단계에서는 production 리소스를 변경하지 않는다.

### Phase C2 — 단일 리소스 실행

- [ ] 단일 volume backup/restore drill
- [ ] 단일 VM 격리 DR drill
- [ ] 제한된 network probe
- [ ] 단일 compute maintenance migration
- [ ] candidate 이미지 build/test

### Phase C3 — 정책·그룹·복구

- [ ] schedule/retention과 다중 리소스 일관성
- [ ] protection group failover/failback
- [ ] topology+probe mismatch 분석
- [ ] maintenance campaign과 max-unavailable
- [ ] official promotion/deprecation/revoke

### Phase C4 — 운영 인수

- [ ] failure drill 전체 통과
- [ ] 사용자/운영자 Horizon UX 검증
- [ ] 감사/알림 end-to-end 검증
- [ ] backup restore 및 DR RPO/RTO 리포트 승인
- [ ] runbook, rollback, on-call ownership 확정
- [ ] 기능별 feature flag와 비상 중지 절차 검증

## 14. 최종 인수 체크리스트

- [ ] 다섯 Workstream 모두 project isolation 보안 시험을 통과했다.
- [ ] 모든 변경 작업에 Operation/Task 타임라인이 존재한다.
- [ ] 모든 중요 상태 변경에 표준 감사 이벤트가 존재한다.
- [ ] 사용자 통지가 작업 성공을 가장하지 않으며 최종 상태와 일치한다.
- [ ] Controller 재시작, API timeout, 중복 요청에서 idempotency가 유지된다.
- [ ] 보상 실패가 숨겨지지 않고 별도 수동 조치 상태로 남는다.
- [ ] 실제 OpenStack 리소스와 control-plane 상태의 drift를 탐지한다.
- [ ] 민감 정보와 다른 프로젝트 topology가 사용자 결과에 노출되지 않는다.
- [ ] production 적용 전에 canary와 rollback 기준이 문서화되어 있다.
- [ ] restore drill, DR drill, maintenance drill, image revoke drill 증거가 보존된다.

이 체크리스트가 모두 충족되어야 Track C를 “구현 완료”로 변경할 수 있다. 단순 API 호출 성공이나 UI 메뉴 노출은 완료 기준이 아니다.
