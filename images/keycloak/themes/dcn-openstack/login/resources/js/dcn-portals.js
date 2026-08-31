const portals = [
  {
    name: "Platform Monitoring",
    nameKo: "플랫폼 모니터링",
    description: "Grafana dashboards",
    descriptionKo: "Grafana 대시보드",
    href: "https://platform.dcn.ssu.ac.kr/grafana/",
  },
  {
    name: "Infrastructure Inventory",
    nameKo: "인프라 자산 관리",
    description: "NetBox inventory",
    descriptionKo: "NetBox 인벤토리",
    href: "https://platform.dcn.ssu.ac.kr/netbox/",
  },
  {
    name: "Cloud Billing",
    nameKo: "클라우드 빌링",
    description: "Public cloud billing portal",
    descriptionKo: "퍼블릭 클라우드 빌링 포털",
    href: "https://billing.dcn.ssu.ac.kr/",
  },
  {
    name: "Source Code",
    nameKo: "소스 코드",
    description: "Gitea repositories",
    descriptionKo: "Gitea 저장소",
    href: "https://platform.dcn.ssu.ac.kr/git/",
  },
  {
    name: "Container Registry",
    nameKo: "컨테이너 레지스트리",
    description: "Harbor images and artifacts",
    descriptionKo: "Harbor 이미지 및 아티팩트",
    href: "https://registry.dcn.ssu.ac.kr/",
  },
];

function createPortalPanel() {
  const container = document.querySelector(".pf-v5-c-login__container");
  const login = container?.querySelector(".pf-v5-c-login__main");
  if (!container || !login || container.querySelector(".dcn-resource-panel")) {
    return;
  }

  const korean = document.documentElement.lang.toLowerCase().startsWith("ko");
  const panel = document.createElement("nav");
  panel.className = "dcn-resource-panel";
  panel.setAttribute("aria-label", korean ? "DCN Cloud 관련 서비스" : "DCN Cloud services");

  for (const portal of portals) {
    const link = document.createElement("a");
    link.className = "dcn-resource-link";
    link.href = portal.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";

    const name = document.createElement("span");
    name.className = "dcn-resource-name";
    name.textContent = korean ? portal.nameKo : portal.name;

    const description = document.createElement("span");
    description.className = "dcn-resource-description";
    description.textContent = korean ? portal.descriptionKo : portal.description;

    const arrow = document.createElement("span");
    arrow.className = "dcn-resource-arrow";
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = "→";

    link.append(name, description, arrow);
    panel.append(link);
  }

  login.insertAdjacentElement("afterend", panel);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", createPortalPanel, { once: true });
} else {
  createPortalPanel();
}
