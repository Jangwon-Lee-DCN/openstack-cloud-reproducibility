# Track B ToDo — Governance, Security, FinOps, Notification

## 1. 문서 목적과 범위

이 문서는 P0/P1 기능 개발을 세 개의 병렬 트랙으로 진행할 때 **Track B가 단독으로
소유할 작업 계약**이다. Track B는 다음 여섯 기능만 구현한다.

1. P0 통합 알림 서비스
2. P1 비용·사용량·예산 관리
3. P1 인증서 수명주기 자동화
4. P1 Secret 자동 Rotation
5. P1 통합 감사 검색
6. P1 공통 Tag 정책

각 기능은 Keystone의 `domain_id`, `project_id`, `user_id`를 권한 경계로 사용하고,
Track A가 제공하는 공통 `Operation/Task` 및 dry-run 계약을 소비한다. OpenStack
원본 서비스 DB를 직접 수정하지 않으며, 기존 서비스 API와 notification/event를
source of truth로 삼는다.

### 성공 상태

- 사용자는 Horizon/API에서 자기 프로젝트의 알림, 비용, 감사 기록을 조회한다.
- 플랫폼은 인증서와 Secret의 만료 전에 안전하게 갱신하고 소비자 반영까지 추적한다.
- 서비스마다 다른 태그 표현을 공통 정책과 검색 모델로 정규화한다.
- 모든 변경 작업은 Track A의 Operation ID로 추적되며 감사 이벤트와 알림이 같은
  correlation ID로 연결된다.
- 운영자만 전체 도메인/프로젝트를 횡단 조회할 수 있고 tenant 간 정보 누출이 없다.

## 2. 병렬 개발 경계와 파일 소유권

### Track B 전용 소유 영역

Track B 에이전트만 아래 신규 경로를 생성·수정한다. 실제 구현 시 디렉터리 이름을
변경해야 한다면 먼저 세 트랙의 담당자와 합의한다.

```text
services/governance-api/**
services/governance-worker/**
images/governance-api/**
images/governance-worker/**
images/horizon-governance-dashboard/**
helm/governance/**
deploy/values/site/governance*.yaml
deploy/tests/governance/**
docs/todo-track-b-governance-security-finops-notification.md
docs/governance-*.md
```

### 공유 파일 변경 규칙

다음 파일은 Track B가 직접 수정하지 않고 별도 통합 커밋의 대상으로 요청한다.

```text
deploy/scripts/build-images.sh
deploy/scripts/reconcile-full-stack.sh
deploy/values/site/horizon.yaml
images/horizon-complete/**
docs/FULL_STACK.md
docs/current-openstack-helm/README.md
```

- Track B 기능의 독립 Horizon panel은 Track B가 소유한다. Track A/C도 자기 기능의
  panel만 소유하며, 공통 navigation과 `horizon-complete` 결합은 통합 담당자가
  순차 반영한다.
- Operation/Task, dry-run, retry, rollback 기반 코드는 Track A가 소유한다.
- 동일 파일을 세 트랙이 동시에 수정하지 않는다.
- DB migration은 Track B 전용 schema/repository에만 추가한다.

## 3. 전체 논리 토폴로지

```text
 User / Operator / Service
          |
          | Keystone token (domain/project/user/roles)
          v
 +--------------------------+       +----------------------------+
 | Horizon / Public API     |------>| Track A Operation API      |
 | per-track panel          |       | task/dry-run/idempotency    |
 +------------+-------------+       +-------------+--------------+
              |                                           |
              v                                           | operation_id
 +---------------------------------------------------------------------+
 |                   Track B Governance API                            |
 | Notification | Cost/Budget | Certificate | Secret | Audit | Tag     |
 +------+-------+-------+------+-------+------+----+----+------+---------+
        |               |              |           |           |
        v               v              v           v           v
  Event/Outbox      Gnocchi/       Barbican +   Audit Store  OpenStack
  + Delivery        Ceilometer/    CA/ACME +    + Index      service APIs
  Worker            CloudKitty     Designate                 + adapters
        |               |              |           ^           |
        v               v              v           |           v
 Email/Webhook    Usage/Rating     Octavia/Ingress |      native tags /
 Alertmanager     Budget Ledger    API consumers   +-- API audit events

 Shared infrastructure:
 - Keystone/Keycloak/OPA: authentication, RBAC/ABAC decision
 - PostgreSQL: desired state, outbox, ledger metadata, rotation state
 - RabbitMQ: event delivery; message body contains IDs, not secrets
 - Prometheus/Alertmanager: platform health and delivery failure alerts
 - Object storage: immutable audit export with retention policy
```

### 데이터 소유 원칙

| 데이터 | Source of truth | Track B 저장 범위 |
| --- | --- | --- |
| 리소스 소유권 | Keystone 및 각 OpenStack API | ID와 조회용 projection |
| 사용량 | Ceilometer/Gnocchi | 집계 bucket, rating 결과, checkpoint |
| 가격 규칙 | CloudKitty 또는 Governance rating catalog | versioned rate card |
| 인증서/Secret 값 | Barbican | secret UUID, version, 상태만 저장 |
| 알림 | Governance DB outbox | payload, 채널 상태, dedup key |
| 감사 원본 | 서비스 audit middleware/event | 정규화 이벤트 및 불변 export |
| 태그 | 각 서비스 API | canonical tag projection과 정책 결과 |

## 4. 공통 API 및 리소스 모델

모든 API는 `/v1`을 사용하고 `X-Openstack-Request-Id`와 Track A의
`operation_id`를 보존한다. 쓰기 요청은 `Idempotency-Key`를 필수로 한다.

### 공통 envelope

```json
{
  "id": "uuid",
  "domain_id": "keystone-domain-id",
  "project_id": "keystone-project-id",
  "created_by": "keystone-user-id",
  "operation_id": "track-a-operation-uuid",
  "created_at": "RFC3339 UTC",
  "updated_at": "RFC3339 UTC",
  "revision": 3
}
```

### 핵심 리소스

| 리소스 | 핵심 필드 | 주요 API |
| --- | --- | --- |
| `Subscription` | event_types, channels, severity, filters, enabled | `GET/POST/PATCH /v1/subscriptions` |
| `Notification` | event_type, resource_ref, severity, dedup_key, deliveries | `GET /v1/notifications`, `POST /{id}/retry` |
| `UsageSummary` | period, service, meter, quantity, unit, source_checkpoint | `GET /v1/usage` |
| `RateCard` | version, effective_at, service, meter, unit_price, currency | operator-only CRUD `/v1/rate-cards` |
| `Budget` | scope, amount, period, thresholds, actions | `/v1/budgets` |
| `CertificatePolicy` | issuer, domains, renew_before, consumers | `/v1/certificate-policies` |
| `RotationPolicy` | secret_ref, cadence, consumers, overlap, rollback | `/v1/rotation-policies` |
| `AuditEvent` | actor, action, target, outcome, policy_decision, request_id | read-only `/v1/audit-events` |
| `TagPolicy` | scope, keys, value schema, enforcement, defaults | `/v1/tag-policies` |

### 공통 상태

Track B가 별도의 범용 task 상태 머신을 만들지 않는다. 변경 작업은 다음과 같이
Track A 상태를 참조한다.

```text
Governance resource desired state
        |
        +--> POST Track A /operations
                  |
                  +--> Validating -> Running -> Succeeded
                                      |             |
                                      +-> Failed / RollingBack -> RolledBack
```

Track B 리소스에는 도메인별 상태(`delivery_status`, `rotation_phase` 등)만 두고,
전체 작업 상태·재시도·진행률은 `operation_id`로 조회한다.

## 5. P0 — 통합 알림 서비스

### 목적

OpenStack/Horizon 작업 완료·실패, quota, 인증서 만료, 백업 실패, 인프라 장애를
사용자별 구독 정책에 따라 Horizon inbox, 이메일, webhook으로 전달한다. 기존
`docs/project-management-notification-contract.md`의 Project Health와 Alertmanager
계약을 폐기하지 않고 수집원으로 연결한다.

### 이벤트 흐름

```text
Nova/Cinder/Neutron/Octavia/Magnum/Track A/Prometheus
                  |
                  v
          Event Normalizer
       (event_type, project_id,
        resource_ref, request_id)
                  |
                  v
       Transactional Outbox DB ----> Dedup/Rate Limit
                  |                         |
                  v                         v
           Delivery Worker -----> Subscription matcher
          /       |       \
 Horizon Inbox  Email   Signed Webhook
                  |
                  +--> delivery result -> AuditEvent + metric
```

### 상세 ToDo

- [ ] Canonical event taxonomy를 정의한다: `operation.*`, `quota.*`,
  `credential.*`, `certificate.*`, `backup.*`, `resource.health.*`,
  `budget.*`, `security.*`.
- [ ] 서비스 notification의 `project_id`, `resource_type`, `resource_id`,
  `request_id` 정규화 adapter를 작성한다.
- [ ] DB transaction과 함께 기록하는 outbox 및 중복 방지 키를 구현한다.
- [ ] 같은 프로젝트·리소스·이벤트의 폭주를 묶는 grouping/rate limit를 구현한다.
- [ ] Horizon inbox read/unread, acknowledge, cursor pagination API를 제공한다.
- [ ] 이메일 template은 한국어/영어, text/html, 안전한 deep link를 지원한다.
- [ ] Webhook은 HMAC 서명, timestamp, replay 방지, exponential backoff와 DLQ를
  지원한다.
- [ ] severity/channel/event별 구독 및 quiet hours를 구현한다.
- [ ] Critical 운영 경보는 Alertmanager가 담당하고, tenant lifecycle 알림과 중복
  전송되지 않게 ownership map을 둔다.
- [ ] receiver credential은 SOPS/Barbican으로 관리하고 Git에 저장하지 않는다.
- [ ] delivery 성공률, 지연, retry, DLQ depth 메트릭과 경보를 추가한다.

### 완료 기준

- [ ] 한 이벤트를 10회 재전달해도 inbox에는 하나만 생성된다.
- [ ] 일시적 SMTP/webhook 장애 후 재시도로 전달되며 중복 side effect가 없다.
- [ ] Project A 토큰으로 Project B의 알림 ID를 추측해도 `404` 또는 `403`이다.
- [ ] webhook 서명이 잘못됐거나 5분 지난 replay 요청은 소비자 예제에서 거절된다.
- [ ] Alertmanager 장애와 Governance delivery 장애를 각각 식별할 수 있다.

## 6. P1 — 비용·사용량·예산

### 목적

사용자가 입력하는 Cost Center 필드가 아니라 실제 meter와 소유권을 기반으로 비용을
산출한다. 초기 단계에서는 청구가 아닌 showback이며, chargeback은 별도 승인 후
활성화한다.

### 수집·정산 흐름

```text
OpenStack resources/events -> Ceilometer -> Gnocchi archive
                                      |
                                      v
                          Usage Aggregator (checkpoint)
                                      |
                           immutable raw aggregation
                                      v
                Versioned RateCard -> Rating -> Cost Ledger
                                                   |
                                  +----------------+----------------+
                                  v                                 v
                          Horizon/API report                  Budget Evaluator
                                                                    |
                                                        Notification event
```

### 상세 ToDo

- [ ] vCPU/RAM 시간, volume/snapshot/backup GiB-hour, Floating IP 시간,
  Load Balancer 시간, object capacity/requests의 meter catalog를 확정한다.
- [ ] meter별 unit, aggregation granularity, 늦게 도착한 sample 처리 규칙을 정의한다.
- [ ] checkpoint 기반 증분 집계와 동일 기간 재실행의 idempotency를 구현한다.
- [ ] rate card 버전·효력 시작일을 저장하고 과거 비용을 새 단가로 소급 변경하지 않는다.
- [ ] 프로젝트/서비스/리소스/tag별 usage와 cost API를 제공한다.
- [ ] 월 예상 비용은 현재 누계와 최근 사용률로 계산하며 `estimate=true`를 명시한다.
- [ ] 월/분기 예산과 50/80/90/100% threshold 이벤트를 구현한다.
- [ ] 데이터 누락·telemetry 지연을 UI가 알 수 있도록 coverage와 watermark를 반환한다.
- [ ] raw aggregate, rated ledger, report의 reconciliation job을 구현한다.
- [ ] 통화·세금·할인·실제 결제는 초기 범위에서 제외한다.

### 완료 기준

- [ ] 고정 fixture를 두 번 집계해도 quantity와 cost가 증가하지 않는다.
- [ ] rate card 변경 전후 기간의 비용이 각 버전으로 재현된다.
- [ ] meter 누락 시 0원으로 숨기지 않고 incomplete 상태를 반환한다.
- [ ] 프로젝트별 합계와 서비스별 합계의 오차가 정의된 반올림 범위 내에서 일치한다.
- [ ] 예산 threshold는 한 구간에서 한 번만 알림을 만들고 다음 기간에 reset된다.

## 7. P1 — 인증서 자동화

### 목적

Barbican을 비밀 저장소로 유지하면서 내부 CA 또는 ACME 발급, DNS-01 검증,
Octavia/Ingress 소비자 반영, 갱신·폐기·만료 알림을 자동화한다.

### 발급 및 갱신 흐름

```text
CertificatePolicy -> Track A validation/operation
        |
        +-> authorization + domain allowlist
        +-> Designate DNS-01 challenge -> CA/ACME
        +-> certificate chain -> Barbican Secret/Container
        +-> consumer adapter (Octavia / approved ingress)
        +-> health check -> activate new version
        +-> overlap window -> retire old version
        +-> AuditEvent + Notification
```

### 상세 ToDo

- [ ] issuer abstraction을 내부 CA와 ACME로 분리한다.
- [ ] 프로젝트가 소유하거나 위임받은 Designate zone만 DNS-01에 사용한다.
- [ ] wildcard, SAN 수, key algorithm/size, validity에 OPA 정책을 적용한다.
- [ ] private key는 worker 메모리 밖의 로그/queue/DB에 평문 기록하지 않는다.
- [ ] Barbican container 버전과 consumer reference를 추적한다.
- [ ] Octavia listener에 새 인증서를 적용한 뒤 TLS probe 성공 시에만 old version을
  폐기한다.
- [ ] `renew_before`, jitter, exponential retry, issuer rate limit을 구현한다.
- [ ] 만료 30/14/7/1일 및 자동 갱신 실패 알림을 생성한다.
- [ ] revoke, compromised key, orphaned DNS challenge 정리 절차를 구현한다.

### 완료 기준

- [ ] DNS-01 레코드는 성공·실패 모두 bounded timeout 후 정리된다.
- [ ] 갱신 중에도 LB TLS 연결이 끊기지 않고 old/new overlap이 보장된다.
- [ ] 권한 없는 zone과 다른 프로젝트 Barbican secret을 참조할 수 없다.
- [ ] 로그와 RabbitMQ 메시지 fixture에서 private key/secret 값이 검출되지 않는다.
- [ ] 발급부터 소비자 반영까지 동일 operation/request ID로 감사 검색된다.

## 8. P1 — Secret 자동 Rotation

### 목적

Application Credential, S3 credential, database/webhook credential 등 회전 가능한
Secret을 새 버전 발급, 소비자 갱신, 검증, 이전 버전 폐기의 2-phase 방식으로
안전하게 교체한다.

### Rotation 흐름

```text
Schedule/manual trigger
        -> create candidate
        -> store candidate in Barbican
        -> update registered consumers
        -> consumer health/auth probe
        -> promote candidate
        -> overlap/grace period
        -> revoke previous
        -> audit + notify
             \ failure -> restore previous consumer refs -> revoke candidate
```

### 상세 ToDo

- [ ] secret type별 rotator와 consumer adapter interface를 정의한다.
- [ ] RotationPolicy에 cadence, overlap, max_age, consumers, rollback 조건을 둔다.
- [ ] candidate/active/retiring/revoked 상태와 version fencing을 구현한다.
- [ ] 일부 소비자만 갱신된 partial failure를 탐지하고 rollback한다.
- [ ] credential 값은 API 응답에서 최초 1회만 노출하거나 전혀 노출하지 않는다.
- [ ] KMS/Barbican 권한, worker service account, network egress를 최소화한다.
- [ ] rotation overdue, consumer drift, rollback failure 알림을 구현한다.
- [ ] break-glass 수동 절차는 다중 승인과 완전한 감사 기록을 요구한다.

### 완료 기준

- [ ] 정상 rotation 중 인증 실패가 없고 이전 credential은 grace 후 거절된다.
- [ ] consumer 한 곳이 실패하면 기존 credential로 완전히 복구된다.
- [ ] 동시에 두 rotation 요청이 와도 revision lock으로 하나만 실행된다.
- [ ] worker 재시작 후 operation checkpoint부터 안전하게 재개된다.
- [ ] DB, 로그, metric label, notification payload에 secret 값이 없다.

## 9. P1 — 통합 감사 검색

### 목적

Keystone, Keycloak/OPA, Horizon, OpenStack API, Track A/B 작업의 행위를 하나의
정규화 모델로 검색하되 원본 무결성과 tenant 격리를 보장한다.

### 감사 흐름

```text
API audit middleware / Keystone / OPA / Track A / Track B
                         |
                  signed event collector
                         |
                 normalize + redact PII
                         |
          append-only audit store -> search index
                         |                |
                         v                v
              immutable object export  Horizon/API query
```

### `AuditEvent` 최소 필드

```text
event_id, occurred_at, received_at, domain_id, project_id,
actor.type/id, source_ip, user_agent, service, action,
target.type/id, outcome, reason_code, policy_decision_id,
request_id, operation_id, changes(redacted), integrity_hash
```

### 상세 ToDo

- [ ] CADF 호환 canonical schema와 서비스별 mapper를 정의한다.
- [ ] request ID와 operation ID 전파 누락률을 측정한다.
- [ ] password, token, cookie, private key, user-data 등 redact 규칙을 denylist가 아닌
  allowlist serializer로 구현한다.
- [ ] append-only 저장, hash chain 또는 서명, immutable object export를 구현한다.
- [ ] actor/action/target/outcome/time/request/operation 필터와 cursor pagination을
  제공한다.
- [ ] tenant 사용자는 자기 프로젝트, domain auditor는 위임된 domain, cloud auditor는
  전체를 조회하도록 OPA 정책을 둔다.
- [ ] 보존·legal hold·삭제 정책과 export manifest를 구현한다.
- [ ] 검색 index 장애 시 원본 수집을 중단하지 않고 backlog를 재처리한다.

### 완료 기준

- [ ] Project A의 검색·export에 Project B 이벤트가 한 건도 나타나지 않는다.
- [ ] 변조된 이벤트/segment는 integrity 검증에서 탐지된다.
- [ ] 정해진 민감정보 corpus가 저장·검색·export 어디에도 노출되지 않는다.
- [ ] API 요청에서 감사 검색 가능 상태까지의 p95 지연 목표를 정의하고 충족한다.
- [ ] index 재구축 결과의 event count/hash가 원본 manifest와 일치한다.

## 10. P1 — 공통 Tag 정책

### 목적

Nova, Cinder, Neutron, Glance, Octavia 등 서로 다른 metadata/tag 표현을 공통
모델로 노출하고, 필수 태그·기본값·검색·비용·정책 연계를 제공한다. 사용자에게
의미 없는 Owner 입력을 받지 않고 소유권은 Keystone에서 자동 결정한다.

### 정책 및 동기화 흐름

```text
Create/Update request
       -> Track A dry-run
       -> Tag Policy resolver (platform/domain/project/resource)
       -> inject system tags + validate user tags
       -> native OpenStack service API
       -> event/poll reconciler
       -> canonical tag projection
          |             |              |
          v             v              v
       Search        Cost split      OPA condition
```

### Canonical tag 규칙

- key는 lowercase `namespace/name` 형식을 권장하며 길이와 문자 집합을 제한한다.
- `system/*`은 플랫폼 전용이며 사용자가 변경할 수 없다.
- `dcn.ssu.ac.kr/project-id`, `domain-id`, `region`, `service`는 소유권/배치에서
  자동 생성한다.
- 사용자 태그에는 secret, credential, 이메일 등 민감값을 금지한다.
- `environment`, `cost-center`는 수동 필수 입력이 아니다. 필요한 조직만 정책으로
  허용하고 신뢰 가능한 그룹/프로젝트 mapping에서 기본값을 주입한다.

### 상세 ToDo

- [ ] 서비스별 native tag/metadata capability matrix를 작성한다.
- [ ] `TagPolicy` precedence를 platform < domain < project 순으로 정의하고 충돌 시
  더 좁은 scope를 적용한다. 단, platform reserved key는 override하지 못한다.
- [ ] required/default/allowed-values/regex/max-count/immutable 규칙을 구현한다.
- [ ] 생성 dry-run에서 최종 주입 태그와 거부 이유를 반환한다.
- [ ] native tag 미지원 리소스는 projection에만 저장하되 UI에 제한을 명시한다.
- [ ] 서비스 이벤트와 정기 reconciliation으로 drift를 탐지한다.
- [ ] 태그 기반 검색과 비용 grouping을 제공한다.
- [ ] 태그를 OPA 입력에 사용할 때 권한 상승이 불가능하도록 trusted/system과
  user-provided tag를 구분한다.

### 완료 기준

- [ ] 사용자 요청에 Owner 필드가 없어도 project/domain system tag가 자동 생성된다.
- [ ] 사용자가 `system/*` 또는 다른 project ID를 주입하면 dry-run에서 거절된다.
- [ ] 각 지원 서비스에서 create/update/delete 후 projection이 수렴한다.
- [ ] 태그별 비용 합계가 프로젝트 총비용과 일치한다.
- [ ] native API에서 발생한 외부 변경도 drift cycle 내에 반영된다.

## 11. Track A 의존성과 Track C·UI 통합 인터페이스

### Track A로부터 필요한 계약

| 필요 항목 | Track B 사용처 | 차단 조건 |
| --- | --- | --- |
| Operation 생성/조회 | 알림 retry, 인증서 발급, rotation, tag reconcile | 안정된 ID/상태 schema 미제공 |
| Idempotency-Key | 모든 Track B 쓰기 API | 재요청 결과 보장 미제공 |
| dry-run result | 인증서, rotation, tag policy, budget 변경 | validation detail schema 미제공 |
| retry/rollback/checkpoint | delivery, certificate, rotation | worker 재시작 복구 계약 미제공 |
| request/correlation 전파 | audit와 알림 연결 | 서비스 경계에서 ID 소실 |

Track A API가 늦어지면 Track B는 adapter interface와 fake server로 개발하되 독자적인
Operation 테이블을 production 경로에 만들지 않는다.

### Track C와 UI 통합 담당에게 제공할 계약

- OpenAPI 문서와 generated client 호환 fixture
- 목록 cursor, filter, sort, empty/loading/error 상태 예제
- 프로젝트 scope와 operator scope별 권한 matrix
- 비용 coverage/watermark, 작업 progress, rotation phase 표시 규칙
- 알림 unread count용 가벼운 endpoint와 polling/cache header
- 감사·비용 export는 비동기 operation으로 시작하고 signed URL은 짧은 TTL 사용
- 태그 editor의 reserved/read-only/validation error schema

Track B는 자기 전용 Horizon panel 밖의 공통 template·navigation을 수정하지 않는다.
Track C와 다른 UI consumer는 Track B DB나 내부 worker endpoint를 직접 호출하지
않고 공개 API/client contract만 사용한다.

## 12. 공통 보안 규칙

- 모든 tenant query는 서버에서 token의 project/domain scope를 강제하며 클라이언트가
  보낸 `project_id`만 신뢰하지 않는다.
- service token과 user token을 구분하고, cross-project 동작은 명시된 system role만
  허용한다.
- OPA 거부는 stable reason code를 반환하되 다른 tenant 리소스 존재 여부를 누출하지
  않는다.
- Secret, token, private key, webhook credential은 로그·metric label·trace·queue에
  기록하지 않는다.
- webhook은 HTTPS, HMAC 서명, timestamp/nonce, 목적지 allowlist와 SSRF 방어를
  필수로 한다.
- 외부 CA/SMTP/webhook egress는 NetworkPolicy와 destination allowlist로 제한한다.
- DB는 TLS, encryption at rest, 최소권한 계정, migration 전용 계정을 사용한다.
- 모든 관리자 변경, break-glass, export, retry, revoke는 감사 이벤트를 생성한다.
- PII는 최소 수집하며 IP/user-agent 보존기간을 별도로 정의한다.
- resource UUID, project UUID 같은 고카디널리티 값은 Prometheus label에 넣지 않는다.

## 13. 통합 테스트 및 인수 게이트

### 자동 테스트

- [ ] schema/OpenAPI breaking-change 검사
- [ ] unit: 분류, 정책 precedence, rating, dedup, redaction
- [ ] property/fuzz: tag 입력, webhook URL, audit filter, money rounding
- [ ] contract: Track A fake/real Operation API, Track C fixture
- [ ] integration: Keystone project isolation, Barbican, Designate, Gnocchi, RabbitMQ
- [ ] failure injection: worker kill, duplicate event, delayed sample, CA/SMTP/index 장애
- [ ] migration upgrade/rollback 및 기존 데이터 보존
- [ ] SAST, dependency/image scan, secret scan, SBOM

### 운영 인수 기준

- [ ] controller 한 대 중단 중 API/worker가 계속 처리되고 중복 결과가 없다.
- [ ] 3개 Rack 배치와 anti-affinity, PDB가 검증된다.
- [ ] backup/restore 후 ledger, policy, outbox, audit manifest가 일치한다.
- [ ] 모든 write 동작이 Operation, AuditEvent, 필요 시 Notification으로 연결된다.
- [ ] tenant 격리 negative test suite가 전부 통과한다.
- [ ] 대량 이벤트/usage 부하에서 정의한 p95와 backlog 회복 시간을 충족한다.
- [ ] runbook, dashboard, alert, rollback 절차가 같이 제공된다.

## 14. 구현 순서와 병렬 가능한 작업

### B0 — 기반 계약

- [ ] OpenAPI, Keystone middleware, project isolation, DB schema
- [ ] Track A adapter/fake, canonical event/audit schema
- [ ] outbox, worker lease, idempotency, metrics 공통 라이브러리

### B1 — P0 알림

- [ ] inbox와 subscription API
- [ ] event adapter, dedup, email/webhook delivery
- [ ] Alertmanager/Project Health 연계 및 운영 검증

### B2 — P1 병렬 묶음

- [ ] 팀 B2-1: usage/rating/budget
- [ ] 팀 B2-2: certificate/secret rotation
- [ ] 팀 B2-3: audit search/tag policy

### B3 — 통합

- [ ] Track C UI contract test
- [ ] Track A real Operation 연동
- [ ] HA/failure/security/performance acceptance
- [ ] 문서와 재현 배포 artifact 고정

## 15. 명시적 제외 사항

다음은 Track B가 구현하지 않는다.

- Launch Template, Auto Scaling, soft delete/trash, 삭제 보호
- 공통 Operation/Task 엔진, dry-run 엔진, generic rollback orchestrator
- Horizon 화면·메뉴·JavaScript와 사용자 생성 wizard
- 자동 백업 정책과 DR orchestration
- 사용자 네트워크 진단, 이미지 공급망, 인스턴스 유지보수
- 실제 결제, 세금계산서, PG 연동, 통화 환전, chargeback 강제 집행
- 퍼블릭 CA 계약 구매와 DNS zone 소유권 이전
- OpenStack 각 프로젝트의 원본 DB 직접 수정
- 모든 legacy Secret의 일괄 rotation: 지원 adapter가 검증된 종류부터 단계적으로 적용
- 감사 데이터에 대한 무제한 보존 또는 사용자 임의 삭제

범위를 넘는 요청은 해당 Track A/C 또는 후속 프로젝트의 issue로 넘기며, Track B
구현에 임시 사본을 만들지 않는다.

## 16. 완료 정의(Definition of Done)

- [ ] 위 여섯 기능의 API, worker, Helm values, migration, runbook이 재현 가능하다.
- [ ] OpenAPI와 권한 matrix가 Track A/C 담당자에게 승인되었다.
- [ ] secret-free Git, image digest 고정, SBOM과 취약점 gate를 통과했다.
- [ ] HA, tenant isolation, retry/idempotency, rollback, backup/restore를 검증했다.
- [ ] dashboard/alert가 장애 원인을 서비스·단계별로 식별한다.
- [ ] production 적용 전 staging에서 발급/rotation/알림/비용/감사/tag end-to-end
  시나리오를 통과했다.
- [ ] 기존 `Project Health`, Alertmanager, Keystone/Keycloak/OPA, Barbican,
  Ceilometer/Gnocchi 동작을 회귀시키지 않는다.

## 17. 개발 구현 기록

### Slice 0.1.0 — API/control model

- [x] tenant-scoped repository, idempotency, canonical audit/redaction 기반
- [x] 알림·구독, usage/rating/budget, 인증서·rotation policy, audit, tag API 모델
- [x] `track-a.operation.v1alpha1` fake adapter 및 versioned contract fixture
- [x] immutable-image-only Helm 차트와 독립 development component
- [x] 단위·HTTP·tenant-negative·secret-redaction·audit-integrity 테스트
- [ ] Keystone/OPA, PostgreSQL HA 및 실제 Track A Operation 연동
- [ ] notification/telemetry/certificate/rotation/audit/tag worker adapter
- [ ] Track B 전용 Horizon panel 및 development end-to-end acceptance

### Slice 0.2.0 — durable workflow contracts

- [x] transactional outbox, expiring lease, retry/backoff 및 DLQ 상태 계약
- [x] SMTP/webhook development fixture, SSRF·DNS rebinding·HMAC·replay 방어
- [x] telemetry checkpoint, immutable raw aggregate 및 Decimal cost ledger
- [x] certificate/secret rotation partial-failure compensation plan
- [x] signed audit ingestion/export와 tamper 검증 fixture
- [x] native tag adapter interface, dry-run 및 drift reconciliation fake
- [x] PostgreSQL transaction/RLS migration과 parameterized repository 계약
- [ ] 실제 PostgreSQL·RabbitMQ 및 외부 서비스 adapter development 통합

### Slice 0.3.0 — complete fake boundary

- [x] 전체 mutable resource CRUD, optimistic revision, idempotency 및 pagination
- [x] API/worker runnable entrypoint와 production-mode fail-closed 설정
- [x] outbox restart recovery 및 deterministic budget/cert/rotation/tag loops
- [x] API·worker container build context 및 immutable digest Helm 입력
- [x] Track B 독립 Horizon panel package와 fake API client contract
- [x] fake-provider E2E, restart/retry/DLQ/security 회귀 suite
- [ ] 실제 provider/identity/database/message bus 및 shared Horizon 통합
- [x] Track A canonical Operation consumer schema 및 대문자 state 정합성
- [x] `track-b.event.v1alpha1` closed canonical schema와 producer drift test

세부 경계, 인수 방법과 rollback은 `docs/governance-development-slice.md`에 기록한다.
위 미완료 항목을 통과하기 전에는 이 슬라이스를 운영 기능으로 표현하거나 운영에
승격하지 않는다.
=======
