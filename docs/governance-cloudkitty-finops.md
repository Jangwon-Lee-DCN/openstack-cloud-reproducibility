# CloudKitty 기반 비용·사용량·예산 운영

## 목적과 경계

이 구성은 실제 결제가 아니라 `DCN-CREDIT` 단위의 showback이다. 사용자가 입력한
Cost Center가 아니라 Keystone project 소유권과 Gnocchi meter를 기준으로 사용량을
산정한다. 세금, 할인, 환율, 결제와 chargeback은 포함하지 않는다.

CloudKitty가 없으면 Governance의 `cloudkitty` provider는 `endpoint_missing`으로
fail-close한다. 미정의 meter는 0원으로 간주하지 않고 원본 aggregate를 보존한 채
`coverage=incomplete` 및 `missing_meters`로 노출한다.

## Topology

```text
Nova/Cinder/Neutron/Glance/Octavia/RGW
                 │ notification/poll
                 ▼
             Ceilometer
                 │ measures + project_id
                 ▼
       Gnocchi archive (source of usage)
                 │ hourly fetch/checkpoint
                 ▼
 ┌──────────────────────────────────────────┐
 │ CloudKitty                               │
 │ API x2              Processor x2         │
 │ /v2/dataframes       Gnocchi collector   │
 │ /v2/summary          Hashmap rate v1     │
 └───────┬──────────────────┬───────────────┘
         │                  ├── MariaDB /cloudkitty
         │                  └── RabbitMQ /cloudkitty
         ▼
 Governance worker
  checkpoint → immutable raw aggregate → Decimal rated ledger
                                    │
                    ┌───────────────┴──────────────┐
                    ▼                              ▼
           GET /v1/usage-summary             Budget evaluator
           project scope + OPA               50/80/90/100%
                                                   │
                                                   ▼
                                      transactional outbox
                                      budget.threshold event
```

Keystone에는 `rating` service, `cloudkitty` service user와 internal/public/admin
endpoint가 `seoul-ssu-1` Region으로 생성된다. API와 processor는 기존 MariaDB,
RabbitMQ, Keystone, Gnocchi만 사용하며 새 데이터 경로를 기존 서비스 DB에 직접
작성하지 않는다.

## Meter 및 rate card

`deploy/config/cloudkitty-rate-card.v1.yaml`이 사람이 검토하는 canonical 정책이다.
Hashmap bootstrap은 같은 이름 `dcn-showback-v1`, 동일 효력 시작일과 단가를
idempotent하게 생성한다. 변경은 기존 mapping을 수정하지 않고 새 version과 새
효력 시작일로 추가해야 한다.

| Meter | 단위 | 목적 |
|---|---|---|
| instance | instance-hour | VM 실행 시간 |
| memory | GiB-hour | VM 메모리 점유 |
| volume.size | GiB-hour | Cinder volume |
| snapshot.size | GiB-hour | snapshot |
| ip.floating | ip-hour | Floating IP |
| network.services.lb | lb-hour | Load Balancer |
| radosgw.objects.size | GiB-hour | Object capacity |

## 배포와 검증

Secret은 `deploy/scripts/generate-cloudkitty-secrets.py`가 기존 암호화된 platform
admin 입력을 사용해 생성한다. 평문은 권한 0600 임시 파일에만 존재하고 항상
삭제되며 Git에는 SOPS ciphertext만 저장한다.

```bash
deploy/scripts/reconcile-cloudkitty.sh check
deploy/scripts/reconcile-cloudkitty.sh diff
# feature -> development -> main 승격 및 exact-main/bootstrap 이후만
deploy/scripts/reconcile-cloudkitty.sh apply
deploy/scripts/reconcile-cloudkitty.sh verify
```

검증은 CloudKitty API/processor rollout, bootstrap Job, endpoint, immutable image와
Keystone catalog를 확인한다. Governance 이미지는 CloudKitty URL을 포함해 새 digest로
빌드하고 공식 `./deploy.sh development p1-governance-services` wrapper로 검증한다.

전용 acceptance project에서는 다음을 순서대로 검증한다.

1. Gnocchi test resource/metric과 bounded-time measure를 만든다.
2. CloudKitty processor가 해당 project dataframe과 summary를 생성할 때까지 기다린다.
3. Governance worker가 checkpoint 이후 frame을 수집하고 Decimal ledger를 만든다.
4. 같은 기간을 두 번 처리해 raw/ledger count와 cost가 증가하지 않는지 확인한다.
5. 예산 threshold outbox/event가 구간별 한 번만 생성되는지 확인한다.
6. test metric/resource/budget을 삭제하고 잔여가 0인지 확인한다.

## 장애와 rollback

- Gnocchi 지연: watermark를 전진시키지 않고 coverage를 incomplete로 유지한다.
- 미정의 meter: raw aggregate는 보존하며 rate card 추가 후 새 immutable ledger
  entry로 후정산한다.
- CloudKitty 장애: Governance readiness와 worker 결과가 blocked가 되며 fake 또는
  0원으로 대체하지 않는다.
- 중복/reprocess: project/sample 및 budget/period/threshold unique key로 무효화한다.
- Helm rollback: `reconcile-cloudkitty.sh rollback`은 직전 accepted revision으로만
  복구한다. DB migration과 ledger는 append-only이므로 downgrade 대신 forward-fix한다.
- 소스 rollback: revert PR 후 동일 check/diff/apply 절차를 사용한다.

CloudKitty 제거는 기존 ledger 삭제를 의미하지 않는다. 데이터 삭제가 필요한 경우
별도의 보존 승인과 백업 검증이 선행되어야 한다.
