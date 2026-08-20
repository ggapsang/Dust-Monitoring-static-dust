---
title: 다임리서치 디자인 시스템
product: 모두의 AI 공장장
themes: [dark, light]
default_theme: dark
brand_color: "#F86517"
typeface: Pretendard
icon_set: Lucide
base_grid: 4px
color_ratio: "6:3:1 (Base : Contents : Accent)"
accessibility: WCAG 2.1 AA
---

# 다임리서치 디자인 시스템

## 1. 개요

### 1.1 목적

다임리서치 웹 제품군에 걸쳐 일관된 사용자 경험을 구현하기 위한 기준 문서다. 디자이너와 개발자가 공통의 원칙과 언어로 협업할 수 있도록 시각 체계와 사용성 기준을 정의하고, 유지보수 가능한 디자인 자산을 제공한다. 이를 통해 제품 전반의 품질과 신뢰도를 높이고, 고객이 빠르고 정확한 판단을 내릴 수 있는 인터페이스 기준을 수립한다.

이 문서는 **다크 모드와 라이트 모드를 함께 정의**한다. 두 테마는 동일한 코어 팔레트와 동일한 시맨틱 토큰명을 공유하며 값만 달라진다. 컴포넌트 구현에는 테마 분기 로직을 넣지 않는다.

### 1.2 대상 독자

| 독자 | 참조 범위 |
|---|---|
| 프로덕트 디자이너 | 전체 |
| 프론트엔드 개발자 | §3 색상 토큰, §4 표면, §7 단위, §8 구현 참조 |
| 외부 협력사 | §3.5 시맨틱 토큰, §3.7 사용 규칙 |

### 1.3 사용 규칙

1. 신규 화면 설계 시 §3 색상, §5 타이포그래피, §7 단위 기준을 먼저 확인한 후 설계를 시작한다.
2. 색상은 **시맨틱 토큰명으로만 참조**한다. 하드코딩된 HEX 값의 직접 사용과 팔레트 외 임의 색상은 허용하지 않는다.
3. 간격·패딩·마진·크기는 §7 단위 스케일에서만 선택한다. 임의의 픽셀 값은 허용하지 않는다.
4. 이 문서에 정의되지 않은 케이스는 임의로 처리하지 않고 내부 협의 후 반영한다.

### 1.4 테마 운영 원칙

- **다크 모드가 제품 기본값**이다. 관제·모니터링 화면은 장시간 주시 환경이므로 다크를 기준으로 설계하고, 라이트를 파생 검증한다.
- **라이트 모드는 다크의 색 반전이 아니다.** 다크는 배경을 밝히는 방식으로 깊이를 만들지만, 라이트는 배경이 이미 최상단 밝기이므로 면의 분리를 그림자와 경계선으로 처리한다. 강조 역시 명도가 아니라 색상 단계로 조절한다.
- 두 테마 모두 WCAG 2.1 AA(본문 4.5:1, 대형 텍스트·비텍스트 요소 3:1)를 충족한다. 이 문서의 모든 대비비는 실측값이다.

---

## 2. 디자인 전략

### 2.1 디자인 목표와 어조

> **모든 공정이 하나의 언어로 연결되는, 신뢰할 수 있는 제어 경험을 만든다.**

| 가치 | 어조 | 시각적 구현 |
|---|---|---|
| **신뢰성** | 정확한 상태 언어 ('정상', '경고', '이상' 등) | 정렬된 그리드, 오차 없는 수치 표현 |
| **명확성** | 짧고 직관적인 레이블 | 정보 위계 강조, 불필요한 장식 제거 |
| **전문성** | 도메인 약어 존중 | 고밀도 데이터의 가독성 확보 |
| **접근성** | 비전문가도 이해 가능한 보조 설명 | 색상 대비 확보, 상태 피드백의 즉시성 |

### 2.2 사용자 경험 원칙

**① 상태 우선 (Status First)**
사용자가 화면을 열었을 때 가장 먼저 행위나 설정의 상태를 파악할 수 있어야 한다. 모든 레이아웃은 상태 표시를 최우선 위계로 배치한다.
- 다크: 어두운 배경 위 상태 색면이 강하게 부각되므로 면적을 절제한다.
- 라이트: 색면의 존재감이 약해지므로 `-50` 배경 + `-700` 전경 + 아이콘 세 요소를 함께 써 면적이 아닌 대비와 형태로 위계를 확보한다.

**② 맥락적 밀도 (Contextual Density)**
화면과 컴포넌트의 맥락, 필요한 정보 밀도를 감안해 설계한다. 컴포넌트는 단순 모드 / 상세 모드처럼 맥락에 따라 다양한 단계를 지원하도록 설계한다. 고밀도 데이터 영역에서 행 구분은 선이 아니라 표면 색(`bg-hover`, `bg-selected`)으로 처리해 시각적 소음을 줄인다.

**③ 신뢰 기반 피드백 (Trustworthy Feedback)**
이상 감지, 알림, 오류 메시지는 **원인 / 위치 / 조치 방법**을 함께 제공한다. 단순히 오류 발생을 알리기만 하는 처리는 허용하지 않는다. 상태를 색상 단독으로 전달하지 않으며 아이콘과 텍스트 레이블을 반드시 병기한다.

**④ 일관된 확장 (Consistent Scaling)**
동일한 디자인 토큰과 컴포넌트를 공유한다. 제품별·화면별 커스텀은 합의와 승인을 통해서만 허용된다.

---

## 3. 색상

### 3.1 브랜드 컬러

| 표기 | 값 |
|---|---|
| HEX | `#F86517` |
| RGB | `248 101 23` |
| HSL | `21 94 53` |
| OKLCH | `0.6844 0.1963 42.6` |

브랜드 컬러는 Primary-500이다. 웹사이트 실사용 색상의 계보를 유지하면서 다크 테마 환경의 접근성 기준을 충족하도록 재정의된 값이다.

| 배경 | 대비비 | 판정 |
|---|---|---|
| 다크 캔버스 `#1C1917` | 5.72 | AA 통과 |
| 다크 패널 `#292524` | 4.96 | AA 통과 |
| 라이트 캔버스 `#F5F5F4` | 2.80 | 미달 |
| White `#FFFFFF` | 3.06 | 미달 (대형 텍스트·비텍스트 요소만) |

즉 **브랜드 오렌지는 다크에서 글자와 면 양쪽으로 쓸 수 있지만, 라이트에서는 면으로만 쓴다.** 라이트 모드에서 선과 글자로 브랜드를 표현할 때는 Primary-700을 사용한다. 이 구분이 두 테마 색상 운용의 가장 큰 차이다.

### 3.2 색상 체계 구조

```
색상 시스템
├─ 코어 색상 (Core)        브랜드의 시각적 정체성을 정의하고 제품의 일관된 인상을 유지
│   ├─ Primary (Brand)     브랜드를 대표하는 핵심 색상. 주요 CTA와 강조 영역
│   └─ Neutral (Stone)     텍스트, 배경, 구분선 등 정보 구조를 지탱하는 기본 색상
└─ 기능 색상 (Functional)  시스템 상태와 사용자 피드백을 명확히 구분
    ├─ Success (Blue)      작업 완료, 정상, 긍정적 결과
    ├─ Warning (Amber)     주의나 확인이 필요한 상태
    └─ Error (Red)         오류·실패 상태, 파괴적 행위(행동 취소 등)의 즉각 인지
```

**색상 사용 원칙**

| 원칙 | 내용 |
|---|---|
| 일관된 원칙으로 사용 | 디자인의 일관성과 사용성의 명확함을 함께 고려하여 색상을 사용한다 |
| 하드코딩 금지 | 색상은 의미 기반 토큰 구조로 참조한다. 하드코딩된 HEX 값의 직접 사용은 금지한다 |
| WCAG 2.1 기준 준수 | 가독성과 접근성이 중요한 주요 색상은 WCAG 2.1 대비 기준을 준수한다 |

순수 Black `#000000` 과 White `#FFFFFF` 의 동시 사용은 명도 대비가 과하고 톤 조정과 명암 표현이 불가능하므로 사용하지 않는다. 각각 Neutral-950 / Neutral-50 으로 대체한다. 단 라이트 모드의 최상위 면(`bg-surface`)과 진한 채움 면 위의 글자에는 White를 단독으로 사용한다.

### 3.3 코어 팔레트

**Primary (Brand)** — 기준 단계 500

| Step | HEX | 다크 용도 | 라이트 용도 |
|---|---|---|---|
| 50 | `#FFF6ED` | 예약 | 선택 행 배경 |
| 100 | `#FFEAD5` | 예약 | 배지 배경, 강조 블록 |
| 200 | `#FED2AA` | 강조 텍스트(subtle 면 위) | 배지 경계선 |
| 300 | `#FDB274` | 차트 계열, subtle 텍스트 | 차트 계열 |
| 400 | `#FA863D` | **브랜드 텍스트·링크·아이콘**, CTA hover | 차트 계열 |
| **500** | **`#F86517`** | **CTA 면, 하이라이트, 포커스 링** | **CTA 면, 하이라이트 바** |
| 600 | `#F14D0D` | CTA pressed | CTA hover, 포커스 링 |
| 700 | `#C2360C` | 예약 | **브랜드 텍스트·링크·아이콘**, CTA pressed |
| 800 | `#9A2C12` | subtle 면 경계 | 배지 내부 강조 텍스트 |
| 900 | `#7C2612` | 예약 | 최고 강조 텍스트 |
| 950 | `#431007` | 선택 행 배경, 배지 배경 | 예약 |

**Neutral (Stone)** — 기준 단계 900

| Step | HEX | 다크 용도 | 라이트 용도 |
|---|---|---|---|
| 50 | `#FAFAF9` | **본문 텍스트** | 예약 |
| 100 | `#F5F5F4` | 예약 | **캔버스 배경** |
| 200 | `#E7E5E4` | 예약 | 구분선, 비활성 면 |
| 300 | `#D6D3D1` | 보조 텍스트 | 약한 경계, 스켈레톤 |
| 400 | `#A3A3A3` | 캡션, placeholder | 비활성 텍스트 |
| 500 | `#78716C` | **컨트롤 경계선** | **컨트롤 경계선**, placeholder |
| 600 | `#57534E` | 강조 경계, 비활성 텍스트 | 캡션·단위 텍스트 |
| 700 | `#44403C` | 구분선, elevated 면 | 레이블·설명 텍스트 |
| 800 | `#292524` | **패널·카드 면** | 예약 |
| **900** | **`#1C1917`** | **캔버스 배경** | **본문 텍스트** |
| 950 | `#0C0A09` | 헤더·GNB 면 | Accent 면 위 텍스트 |

**기능 색상**

| Step | Success (Blue) | Warning (Amber) | Error (Red) |
|---|---|---|---|
| 50 | `#EFF6FF` | `#FEFCE8` | `#FEF2F2` |
| 100 | `#DBEAFE` | `#FEF3C7` | `#FEE2E2` |
| 200 | `#BFDBFE` | `#FDE68A` | `#FECACA` |
| 300 | `#93C5FD` | `#FCD34D` | `#FCA5A5` |
| 400 | `#60A5FA` | `#FBBF24` | `#F87171` |
| **500** | **`#3B82F6`** | **`#F59E0B`** | **`#EF4444`** |
| 600 | `#2563EB` | `#D97706` | `#DC2626` |
| 700 | `#1D4ED8` | `#B45309` | `#B91C1C` |
| 800 | `#1E40AF` | `#92400E` | `#991B1B` |
| 900 | `#1E3A8A` | `#78350F` | `#7F1D1D` |
| 950 | `#172554` | `#451A03` | `#450A0A` |

기능 색상은 **다크에서 `-400`, 라이트에서 `-700`** 을 전경색으로 사용한다. `-500`은 양쪽 테마 모두 채움 면과 인디케이터 도트 전용이며 텍스트로 쓰지 않는다.

**Black & White**

| 토큰 | HEX | 용도 |
|---|---|---|
| black | `#000000` | 사용하지 않음 (Neutral-950로 대체) |
| white | `#FFFFFF` | 라이트 모드 surface, 진한 채움 면 위 텍스트 |

### 3.4 면 구조

```
[다크]                                  [라이트]
bg-header    Neutral-950  #0C0A09       bg-header    White + 하단 경계선
bg-base      Neutral-900  #1C1917       bg-base      Neutral-100  #F5F5F4
 └ bg-surface  Neutral-800 #292524       └ bg-surface  White #FFFFFF + shadow-1
    └ bg-elevated Neutral-700 #44403C       └ bg-elevated White + shadow-2
```

- **다크**는 위로 올라갈수록 밝아지는 명도 계단으로 층위를 만든다. 단 인접 단계 간 대비비가 1.15:1(900↔800), 1.48:1(800↔700)로 미세하므로 `border-divider`를 함께 사용해 경계를 명시한다.
- **라이트**는 White와 Neutral-100의 대비비가 1.09:1로 면 자체만으로 구분되지 않는다. 따라서 **모든 surface는 `border-divider` 1px 또는 `shadow-1` 이상을 반드시 동반**한다. 그림자도 경계선도 없는 흰 카드를 흰 배경 위에 놓지 않는다.

### 3.5 시맨틱 토큰

두 테마가 같은 토큰명을 쓰고 값만 달라진다. 괄호 안은 해당 테마의 기본 면(다크 = `bg-surface` Neutral-800, 라이트 = `bg-surface` White) 기준 실측 대비비다.

**배경**

| 토큰 | 다크 | 라이트 | 용도 |
|---|---|---|---|
| `bg-base` | Neutral-900 `#1C1917` | Neutral-100 `#F5F5F4` | 캔버스, 최하위 배경 |
| `bg-surface` | Neutral-800 `#292524` | White `#FFFFFF` | 패널, 카드, 테이블 본문 |
| `bg-elevated` | Neutral-700 `#44403C` | White + `shadow-2` | 드롭다운, 팝오버, 모달 |
| `bg-header` | Neutral-950 `#0C0A09` | White + 하단 `border-divider` | GNB, 사이드바, 테이블 헤더 |
| `bg-input` | Neutral-900 `#1C1917` | White `#FFFFFF` | 입력 필드 |
| `bg-hover` | Neutral-700 `#44403C` | Neutral-100 `#F5F5F4` | 행·항목 hover |
| `bg-active` | Neutral-600 `#57534E` | Neutral-200 `#E7E5E4` | 눌림 상태 |
| `bg-selected` | Primary-950 `#431007` | Primary-50 `#FFF6ED` | 선택된 행·항목 |
| `bg-disabled` | Neutral-800 `#292524` | Neutral-200 `#E7E5E4` | 비활성 면 |

**텍스트**

| 토큰 | 다크 (대비비) | 라이트 (대비비) | 용도 |
|---|---|---|---|
| `text-primary` | Neutral-50 `#FAFAF9` (14.52) | Neutral-900 `#1C1917` (17.49) | 본문, 주요 수치, 제목 |
| `text-secondary` | Neutral-300 `#D6D3D1` (10.18) | Neutral-700 `#44403C` (10.27) | 레이블, 설명문 |
| `text-tertiary` | Neutral-400 `#A3A3A3` (6.01) | Neutral-600 `#57534E` (7.63) | 캡션, 단위, 메타 정보 |
| `text-placeholder` | Neutral-400 `#A3A3A3` (6.01) | Neutral-500 `#78716C` (4.80) | 입력 필드 placeholder |
| `text-disabled` | Neutral-600 `#57534E` (1.99) | Neutral-400 `#A3A3A3` (2.52) | 비활성 텍스트 |
| `text-brand` | Primary-400 `#FA863D` (6.17) | Primary-700 `#C2360C` (5.49) | 브랜드 텍스트, 링크, 강조 아이콘 |
| `text-on-accent` | Neutral-950 `#0C0A09` (6.46) | Neutral-950 `#0C0A09` (6.46) | Accent 면 위 텍스트 |
| `text-on-solid` | White `#FFFFFF` | White `#FFFFFF` (5.49) | 진한 채움 면 위 텍스트 |

`text-disabled`는 WCAG 대비 요구가 면제되는 비활성 컨트롤에만 사용한다. 읽어야 하는 정보에는 사용하지 않는다.

**경계선**

| 토큰 | 다크 (대비비) | 라이트 (대비비) | 용도 |
|---|---|---|---|
| `border-divider` | Neutral-700 `#44403C` | Neutral-200 `#E7E5E4` | 구분선, 테이블 라인, 카드 외곽 |
| `border-control` | Neutral-500 `#78716C` (3.16) | Neutral-500 `#78716C` (4.80) | 입력·선택 컨트롤 경계 |
| `border-strong` | Neutral-400 `#A3A3A3` (6.01) | Neutral-700 `#44403C` (10.27) | 강조 경계, 활성 컨트롤 |
| `border-focus` | Primary-500 `#F86517` (4.96) | Primary-600 `#F14D0D` (3.62) | 포커스 링 |

조작 가능한 컨트롤의 경계는 WCAG 2.1 비텍스트 대비 기준(3:1)을 충족해야 한다. 양 테마 모두 Neutral-500이 이 기준을 만족하므로 `border-control`은 테마와 무관하게 동일한 값을 쓴다. `border-divider`는 조작 대상이 아닌 장식적 구분선에만 사용한다.

**Accent**

| 토큰 | 다크 | 라이트 | 용도 |
|---|---|---|---|
| `accent-fill` | Primary-500 `#F86517` | Primary-500 `#F86517` | 주요 CTA 면, 하이라이트 바, 활성 인디케이터 |
| `accent-fill-hover` | Primary-400 `#FA863D` | Primary-600 `#F14D0D` | CTA hover |
| `accent-fill-pressed` | Primary-600 `#F14D0D` | Primary-700 `#C2360C` | CTA pressed |
| `accent-subtle` | Primary-950 `#431007` | Primary-100 `#FFEAD5` | 배지 배경, 강조 블록 |
| `accent-subtle-border` | Primary-800 `#9A2C12` | Primary-200 `#FED2AA` | 배지 경계 |
| `accent-subtle-text` | Primary-300 `#FDB274` (8.97) | Primary-800 `#9A2C12` (6.56) | `accent-subtle` 면 위 텍스트 |

Accent 면(`accent-fill`)은 두 테마 모두 브랜드 컬러 그대로 유지한다. **면 위 라벨은 양 테마 모두 `text-on-accent`(Neutral-950)를 쓴다.** Primary-500 위의 White는 3.06:1로 미달한다. hover 방향만 반대인데, 다크에서는 밝아지고(400) 라이트에서는 어두워진다(600).

**상태**

| 토큰 | 다크 (대비비) | 라이트 (대비비) |
|---|---|---|
| `status-success-fg` | Success-400 `#60A5FA` (5.97) | Success-700 `#1D4ED8` (6.70) |
| `status-success-bg` | Success-950 `#172554` | Success-50 `#EFF6FF` |
| `status-success-border` | Success-800 `#1E40AF` | Success-200 `#BFDBFE` |
| `status-success-solid` | Success-600 `#2563EB` | Success-600 `#2563EB` |
| `status-warning-fg` | Warning-400 `#FBBF24` (9.09) | Warning-700 `#B45309` (5.02) |
| `status-warning-bg` | Warning-950 `#451A03` | Warning-50 `#FEFCE8` |
| `status-warning-border` | Warning-800 `#92400E` | Warning-200 `#FDE68A` |
| `status-warning-solid` | Warning-500 `#F59E0B` | Warning-500 `#F59E0B` |
| `status-error-fg` | Error-400 `#F87171` (5.48) | Error-700 `#B91C1C` (6.47) |
| `status-error-bg` | Error-950 `#450A0A` | Error-50 `#FEF2F2` |
| `status-error-border` | Error-800 `#991B1B` | Error-200 `#FECACA` |
| `status-error-solid` | Error-600 `#DC2626` | Error-600 `#DC2626` |

채움 면 위 텍스트: Success-600 + White = 5.17, Error-600 + White = 4.83, Warning-500 + Neutral-950 = 9.20. 세 경우 모두 양 테마 공통이다.

전경색 단계는 테마별로 통일한다. 다크는 전 계열 `-400`, 라이트는 전 계열 `-700`이다. 계열별로 단계를 다르게 가져가지 않는다. 특히 Warning-500은 밝은 배경에서 2.15:1로 판독이 불가능하므로 라이트 모드 텍스트에 절대 사용하지 않는다.

### 3.6 6:3:1 색상 비율

다임리서치 제품의 화면은 6:3:1 색상 비율 원칙을 기반으로 설계한다.

| 비율 | 구성 | 역할 |
|---|---|---|
| **6** | Base — `bg-base`, `bg-surface` | 여백과 안정감 |
| **3** | Contents — `text-primary`, `text-secondary`, `border-divider` | 명료한 정보 전달 |
| **1** | Accent — `accent-fill`, `text-brand` | 사용자의 주의를 자연스럽게 유도 |

Accent가 화면에서 차지하는 면적은 10%를 넘지 않는다. 상태 색상은 Accent 예산과 별도로 취급하되, 한 화면에 상태 색이 동시에 여러 종 노출되면 식별성이 무너지므로 위계를 정리해 노출한다.

### 3.7 사용 규칙과 금지 조합

**공통 규칙**

1. Accent 면 위 라벨은 `text-on-accent`(Neutral-950)를 쓴다. White 라벨이 필요하면 면을 Primary-700 이상으로 낮추고 `text-on-solid`를 쓴다.
2. 상태는 색·아이콘·텍스트 세 요소를 함께 전달한다. 색상 단독 전달을 금지한다.
3. 조작 가능한 컨트롤의 경계는 3:1 이상을 확보한다.
4. `-500` 단계 기능 색상은 채움 면과 도트에만 쓴다.
5. Black + White 동시 사용을 금지한다.

**테마별 규칙**

| 구분 | 다크 | 라이트 |
|---|---|---|
| 브랜드 표현 | Primary-500을 글자·선·면 모두에 사용 가능 | Primary-500은 면 전용. 글자·선은 Primary-700 |
| 깊이 표현 | 명도 계단 + `border-divider` | 그림자 + `border-divider` |
| CTA hover 방향 | 밝게 (500 → 400) | 어둡게 (500 → 600) |
| 기능 색 전경 | `-400` | `-700` |
| 큰 색면 | 넓은 채도 면은 눈부심을 유발하므로 절제 | 색면 존재감이 약하므로 경계선으로 보강 |

**금지 조합**

| 금지 | 대비비 | 테마 | 대체 |
|---|---|---|---|
| Primary-500 텍스트 on 밝은 배경 | 3.06 / 2.80 | 라이트 | `text-brand` (Primary-700) |
| Primary-500 을 라이트 포커스 링·컨트롤 경계로 사용 | 2.80 (캔버스 기준) | 라이트 | `border-focus` (Primary-600) |
| Primary-500 면 + White 라벨 | 3.06 | 공통 | `text-on-accent` (Neutral-950) |
| Warning-500 텍스트 | 2.15 | 라이트 | `status-warning-fg` (Warning-700) |
| Success-500 / Error-500 본문 텍스트 | 3.68 / 3.76 | 라이트 | `-700` 단계 |
| Neutral-500 을 다크 본문·placeholder로 사용 | 3.16 | 다크 | Neutral-400 |
| Neutral-400 을 라이트 본문으로 사용 | 2.52 | 라이트 | `text-tertiary` (Neutral-600) |
| Neutral-200 / 300 을 컨트롤 경계로 사용 | 1.26 / 1.49 | 라이트 | `border-control` (Neutral-500) |
| Neutral-700 을 다크 컨트롤 경계로 사용 | 1.48 | 다크 | `border-control` (Neutral-500) |
| 그림자·경계 없는 흰 카드 on 캔버스 | 1.09 | 라이트 | `shadow-1` 또는 `border-divider` 동반 |
| Black `#000000` + White `#FFFFFF` 동시 사용 | — | 공통 | Neutral-950 / Neutral-50 |

### 3.8 컴포넌트 색상 적용

| 컴포넌트 | 면 | 텍스트 | 경계 |
|---|---|---|---|
| Primary 버튼 | `accent-fill` | `text-on-accent` | 없음 |
| Secondary 버튼 | `bg-surface` | `text-primary` | `border-control` |
| Tertiary(텍스트) 버튼 | 투명 → hover `bg-hover` | `text-brand` | 없음 |
| Destructive 버튼 | `status-error-solid` | `text-on-solid` | 없음 |
| 입력 필드 | `bg-input` | `text-primary` / `text-placeholder` | `border-control` → focus `border-focus` 2px |
| 테이블 헤더 | `bg-header` | `text-tertiary` | 하단 `border-divider` |
| 테이블 행 | `bg-surface` → hover `bg-hover` → 선택 `bg-selected` | `text-primary` | 행간 `border-divider` |
| 상태 배지 | `status-*-bg` | `status-*-fg` | `status-*-border` |
| 상태 인디케이터 도트 | `status-*-solid` | 레이블은 `text-secondary` | 없음 |
| 알림 배너 | `status-*-bg` | 제목 `status-*-fg`, 본문 `text-secondary` | 좌측 4px `status-*-solid` |
| 모달 | `bg-elevated` (+ 라이트 `shadow-3`) | `text-primary` | 다크 `border-divider` |
| 툴팁 | 다크 Neutral-700 / 라이트 Neutral-900 | 다크 `text-primary` / 라이트 White | 없음 |

툴팁은 라이트 모드에서 유일하게 반전 면을 사용한다. 일시적 요소이므로 배경 위계를 침범하지 않기 위한 처리다.

### 3.9 레거시 토큰 대응

기존 제품에서 사용하던 쿨톤(slate) 계열 토큰의 대응표다. 마이그레이션 시 배경 색온도가 쿨톤에서 웜톤(stone)으로 바뀌어 화면 전체 인상이 달라지므로, 부분 교체가 아닌 일괄 교체로 진행한다.

| 레거시 | HEX | 신규 시맨틱 토큰 | 다크 값 |
|---|---|---|---|
| primary-hover | `#FFA256` | `accent-fill-hover` | Primary-400 `#FA863D` |
| primary-main | `#F28C38` | `accent-fill` | Primary-500 `#F86517` |
| primary-dark | `#D4701F` | `accent-fill-pressed` | Primary-600 `#F14D0D` |
| text-primary | `#FFFFFF` | `text-primary` | Neutral-50 `#FAFAF9` |
| text-secondary | `#A0A6B1` | `text-secondary` | Neutral-300 `#D6D3D1` |
| border | `#4A505A` | `border-divider` | Neutral-700 `#44403C` |
| bg-input | `#424751` | `bg-input` | Neutral-900 `#1C1917` |
| bg-canvas | `#383C45` | `bg-base` | Neutral-900 `#1C1917` |
| bg-panel | `#282C34` | `bg-surface` | Neutral-800 `#292524` |
| bg-header | `#1E2228` | `bg-header` | Neutral-950 `#0C0A09` |

---

## 4. 표면과 깊이 (Elevation)

| 토큰 | 다크 | 라이트 |
|---|---|---|
| `elev-0` | `bg-base` | `bg-base`, 그림자 없음 |
| `elev-1` | `bg-surface` + `border-divider` | `bg-surface` + `shadow-1` |
| `elev-2` | `bg-elevated` + `border-divider` | `bg-surface` + `shadow-2` |
| `elev-3` | `bg-elevated` + `shadow-3` | `bg-surface` + `shadow-3` |
| `elev-4` | `bg-elevated` + `shadow-4` | `bg-surface` + `shadow-4` |

**그림자 값**

| 토큰 | 다크 | 라이트 |
|---|---|---|
| `shadow-1` | `0 1px 2px rgba(0,0,0,0.30)` | `0 1px 2px rgba(12,10,9,0.06), 0 1px 3px rgba(12,10,9,0.10)` |
| `shadow-2` | `0 4px 8px rgba(0,0,0,0.36)` | `0 2px 4px rgba(12,10,9,0.06), 0 4px 8px rgba(12,10,9,0.08)` |
| `shadow-3` | `0 12px 24px rgba(0,0,0,0.44)` | `0 4px 8px rgba(12,10,9,0.08), 0 12px 24px rgba(12,10,9,0.12)` |
| `shadow-4` | `0 20px 40px rgba(0,0,0,0.52)` | `0 20px 40px rgba(12,10,9,0.16)` |

- 다크 모드에서 깊이의 1차 수단은 그림자가 아니라 **면의 명도 상승**이다. 그림자는 모달·토스트 등 캔버스에서 완전히 분리되어야 하는 요소에만 사용한다.
- 라이트 모드에서는 명도를 더 높일 여지가 없으므로 그림자가 1차 수단이다. 그림자 색은 무채색 대신 Neutral-950 기반 알파를 써 웜톤 계열을 유지한다.
- 오프셋과 블러는 4px 그리드에서 파생한다. 한 화면에서 3단계 이상의 그림자를 동시에 노출하지 않는다.
- 고밀도 데이터 테이블 내부 요소에는 그림자를 쓰지 않고 `border-divider`로만 구분한다.
- 포커스 링은 그림자가 아니라 `outline: 2px solid var(--border-focus); outline-offset: 2px` 로 구현한다.

---

## 5. 타이포그래피

### 5.1 서체

디지털 환경에서의 가독성과 확장성을 우선하여 **Pretendard**를 기본 서체로 사용한다. 기존 웹사이트에서 사용하던 Noto Sans KR의 고딕 계열 구조를 계승하여 시각적으로 이질감 없이 연속되며, 한글과 영문 자형의 통일감이 높아 기술 용어 혼용 환경에 적합하다. 오픈소스(OFL) 서체로 라이선스 비용 없이 사용·배포가 가능하다.

```css
font-family: "Pretendard Variable", Pretendard, -apple-system, system-ui, sans-serif;
```

| 명칭 | font-weight |
|---|---|
| Light | 300 |
| Regular | 400 |
| Medium | 500 |
| SemiBold | 600 |
| Bold | 700 |

**Noto Sans KR 대비**

| 구분 | Noto Sans KR (기존 웹사이트) | Pretendard (제품 적용) |
|---|---|---|
| 계열 | 고딕체 / 범용 산세리프 | 모던 산세리프 (고딕 기반 최적화) |
| 특징 | 다국어 지원 중심, 자간 넓음 | 명료한 가독성, 디스플레이 화면 중심 설계 |
| 라이선스 | 오픈소스(OFL), 무료, CDN 배포 | 오픈소스(OFL), 무료, CDN 배포 |
| 적합 환경 | 다국어 문서, 범용 콘텐츠 | 디지털 제품, 웹/앱 UI 환경 |
| 한영 혼용 | 한글/영문 자형 이질감 있음 | 자형 통일감, 기술 용어 혼용에 최적 |
| 제품 적합성 | 범용적이나 기술 B2B에 중립적 | 딥테크 B2B 제품 정체성과 일치 |

### 5.2 사이즈 스케일

| 토큰 | Size | Line height | 권장 용도 |
|---|---|---|---|
| `text-xs` | 12px | 16px | 캡션, 단위, 테이블 메타 |
| `text-sm` | 14px | 20px | 고밀도 테이블 본문, 보조 레이블 |
| `text-base` | 16px | 24px | 기본 본문 |
| `text-lg` | 18px | 28px | 강조 본문, 카드 제목 |
| `text-xl` | 20px | 28px | 섹션 소제목 |
| `text-2xl` | 24px | 32px | 패널 제목 |
| `text-3xl` | 30px | 36px | 페이지 제목 |
| `text-4xl` | 36px | 40px | 대시보드 KPI 수치 |
| `text-5xl` | 48px | 48px | 대형 수치, 관제 화면 |
| `text-6xl` | 60px | 60px | 대형 수치 |
| `text-7xl` | 72px | 72px | 사이니지, 대형 디스플레이 |
| `text-8xl` | 96px | 96px | 사이니지 |
| `text-9xl` | 128px | 128px | 사이니지 |

모든 단계에 Light / Regular / Medium / SemiBold / Bold 5종이 정의된다. `text-5xl` 이상은 line-height가 font-size와 동일하다.

### 5.3 테마별 가독성 기준

- 다크 배경에서는 흰 글자가 실제보다 굵고 번져 보인다(광학적 팽창). 반대로 라이트 배경에서는 검은 글자가 가늘게 보인다. **같은 굵기를 두 테마에 그대로 적용하는 것이 기준이며**, 테마별로 굵기를 임의 조정하지 않는다.
- Light(300)는 `text-4xl` 이상에서만 사용한다. 특히 다크 모드의 `text-base` 이하에서 Light를 쓰면 획이 번져 판독이 저하된다.
- 수치·단위·설비 ID 등 오독이 치명적인 값은 `text-primary` + Medium 이상으로 표기한다.
- 대형 수치(`text-4xl` 이상)에 Accent 색을 적용할 경우 `text-brand`를 사용한다. 라이트 모드에서 Primary-500은 이 크기에서도 본문 대비 기준을 만족하지 못한다.

---

## 6. 아이콘

| 항목 | 규격 |
|---|---|
| 리소스 | Lucide icons |
| 형식 | SVG |
| 기준 크기 | 24 × 24 px |
| 그리드 | 24px grid |
| 스타일 | Line-based |
| 스트로크 | 1.5px centered-stroke |
| 내부 여백 | 2px inner spacing (실제 도형 영역 20 × 20) |

**핵심 원칙**

- **일관성** — 모든 화면과 컴포넌트에서 동일한 선 굵기·비율·시각 규칙을 유지해 사용자가 학습 없이 즉시 인식할 수 있게 한다.
- **명료성** — 불필요한 장식 없이 핵심 의미만 전달하며, 소형 아이콘부터 고해상도 디스플레이까지 선명하게 인지된다.
- **직관성** — 형태가 기능과 동작을 자연스럽게 암시하도록 설계해 별도 설명 없이 의미를 파악할 수 있게 한다.

**톤**

| 구분 | 내용 |
|---|---|
| 시각톤 | 과도한 각짐 없이 자연스럽게 처리된 곡선으로 기술적 정밀함과 접근성을 동시에 전달 |
| 표현 톤 | 획 굵기와 여백으로 의미를 완성하고 장식적 요소를 배제해 산업용 UI 맥락에 부합 |
| 형태 톤 | 24px 그리드 위 정렬된 비례로 설계되어 어떤 배경색과 크기에서도 시각적 안정감 유지 |

**테마 적용**

- 색상은 `stroke="currentColor"`로 상속받아 §3.5 텍스트 토큰을 그대로 따른다. 아이콘 전용 색을 별도로 정의하지 않는다.
- 기본 `text-tertiary`, 조작 가능 상태 `text-secondary`, 활성·강조 `text-brand`, 상태 아이콘 `status-*-fg`를 사용한다.
- 16px 이하로 축소할 때 스트로크를 비례 축소하지 않는다. `vector-effect="non-scaling-stroke"`를 사용하거나 사이즈별 전용 스트로크 값을 적용해 시각 굵기를 유지한다.
- 상태 아이콘은 형태로도 구분되어야 한다. Success는 체크, Warning은 삼각형, Error는 원형·엑스 계열로 고정해 색상 없이도 판별 가능하게 한다.

---

## 7. 단위 및 간격

모든 UI 속성은 **4px 베이스 그리드**에서 파생된 단위 시스템으로 정의한다. 모든 간격, 패딩, 마진, 컴포넌트 크기는 이 스케일에서만 선택하며 임의의 픽셀 값은 허용하지 않는다. 이 규칙은 단순한 픽셀 수치가 아니라 정보 구조의 질서와 사용자 인지의 흐름을 제어하는 기준으로 작동한다.

`unit-N` = `N × 4px` (단, `unit-0.5` = 2px)

| 토큰 | px | 토큰 | px | 토큰 | px |
|---|---|---|---|---|---|
| `unit-0.5` | 2 | `unit-9` | 36 | `unit-72` | 288 |
| `unit-1` | 4 | `unit-10` | 40 | `unit-80` | 320 |
| `unit-1.5` | 6 | `unit-12` | 48 | `unit-96` | 384 |
| `unit-2` | 8 | `unit-14` | 56 | `unit-112` | 448 |
| `unit-2.5` | 10 | `unit-16` | 64 | `unit-128` | 512 |
| `unit-3` | 12 | `unit-18` | 72 | `unit-144` | 576 |
| `unit-3.5` | 14 | `unit-20` | 80 | `unit-160` | 640 |
| `unit-4` | 16 | `unit-24` | 96 | `unit-192` | 768 |
| `unit-4.5` | 18 | `unit-28` | 112 | `unit-224` | 896 |
| `unit-5` | 20 | `unit-32` | 128 | `unit-256` | 1024 |
| `unit-6` | 24 | `unit-36` | 144 | `unit-288` | 1152 |
| `unit-7` | 28 | `unit-40` | 160 | `unit-320` | 1280 |
| `unit-8` | 32 | `unit-48` | 192 | `unit-384` | 1536 |
| | | `unit-56` | 224 | `unit-448` | 1792 |
| | | `unit-60` | 240 | `unit-512` | 2048 |
| | | `unit-64` | 256 | `unit-576` | 2304 |
| | | | | `unit-640` | 2560 |

| 구간 | 용도 |
|---|---|
| `unit-0.5` ~ `unit-10` | 컴포넌트 내부 간격, 패딩, 아이콘-텍스트 갭 |
| `unit-12` ~ `unit-96` | 섹션 간격, 레이아웃 갭, 컴포넌트 높이 |
| `unit-112` 이상 | 컨테이너 폭, 최대 너비, 패널 크기 |

---

## 8. 구현 참조

### 8.1 CSS 커스텀 프로퍼티

```css
/* ── 코어 팔레트 (원시 토큰. 컴포넌트에서 직접 참조하지 않는다) ── */
:root {
  --primary-50:#FFF6ED;  --primary-100:#FFEAD5; --primary-200:#FED2AA;
  --primary-300:#FDB274; --primary-400:#FA863D; --primary-500:#F86517;
  --primary-600:#F14D0D; --primary-700:#C2360C; --primary-800:#9A2C12;
  --primary-900:#7C2612; --primary-950:#431007;

  --neutral-50:#FAFAF9;  --neutral-100:#F5F5F4; --neutral-200:#E7E5E4;
  --neutral-300:#D6D3D1; --neutral-400:#A3A3A3; --neutral-500:#78716C;
  --neutral-600:#57534E; --neutral-700:#44403C; --neutral-800:#292524;
  --neutral-900:#1C1917; --neutral-950:#0C0A09;

  --success-50:#EFF6FF;  --success-100:#DBEAFE; --success-200:#BFDBFE;
  --success-300:#93C5FD; --success-400:#60A5FA; --success-500:#3B82F6;
  --success-600:#2563EB; --success-700:#1D4ED8; --success-800:#1E40AF;
  --success-900:#1E3A8A; --success-950:#172554;

  --warning-50:#FEFCE8;  --warning-100:#FEF3C7; --warning-200:#FDE68A;
  --warning-300:#FCD34D; --warning-400:#FBBF24; --warning-500:#F59E0B;
  --warning-600:#D97706; --warning-700:#B45309; --warning-800:#92400E;
  --warning-900:#78350F; --warning-950:#451A03;

  --error-50:#FEF2F2;    --error-100:#FEE2E2;   --error-200:#FECACA;
  --error-300:#FCA5A5;   --error-400:#F87171;   --error-500:#EF4444;
  --error-600:#DC2626;   --error-700:#B91C1C;   --error-800:#991B1B;
  --error-900:#7F1D1D;   --error-950:#450A0A;

  --font-sans: "Pretendard Variable", Pretendard, -apple-system, system-ui, sans-serif;
}

/* ── 다크 모드 (제품 기본) ── */
[data-theme="dark"] {
  --bg-base:      var(--neutral-900);
  --bg-surface:   var(--neutral-800);
  --bg-elevated:  var(--neutral-700);
  --bg-header:    var(--neutral-950);
  --bg-input:     var(--neutral-900);
  --bg-hover:     var(--neutral-700);
  --bg-active:    var(--neutral-600);
  --bg-selected:  var(--primary-950);
  --bg-disabled:  var(--neutral-800);

  --text-primary:     var(--neutral-50);
  --text-secondary:   var(--neutral-300);
  --text-tertiary:    var(--neutral-400);
  --text-placeholder: var(--neutral-400);
  --text-disabled:    var(--neutral-600);
  --text-brand:       var(--primary-400);
  --text-on-accent:   var(--neutral-950);
  --text-on-solid:    #FFFFFF;

  --border-divider: var(--neutral-700);
  --border-control: var(--neutral-500);
  --border-strong:  var(--neutral-400);
  --border-focus:   var(--primary-500);

  --accent-fill:          var(--primary-500);
  --accent-fill-hover:    var(--primary-400);
  --accent-fill-pressed:  var(--primary-600);
  --accent-subtle:        var(--primary-950);
  --accent-subtle-border: var(--primary-800);
  --accent-subtle-text:   var(--primary-300);

  --status-success-fg:     var(--success-400);
  --status-success-bg:     var(--success-950);
  --status-success-border: var(--success-800);
  --status-success-solid:  var(--success-600);

  --status-warning-fg:     var(--warning-400);
  --status-warning-bg:     var(--warning-950);
  --status-warning-border: var(--warning-800);
  --status-warning-solid:  var(--warning-500);

  --status-error-fg:     var(--error-400);
  --status-error-bg:     var(--error-950);
  --status-error-border: var(--error-800);
  --status-error-solid:  var(--error-600);

  --shadow-1: 0 1px 2px rgba(0,0,0,0.30);
  --shadow-2: 0 4px 8px rgba(0,0,0,0.36);
  --shadow-3: 0 12px 24px rgba(0,0,0,0.44);
  --shadow-4: 0 20px 40px rgba(0,0,0,0.52);
}

/* ── 라이트 모드 ── */
[data-theme="light"] {
  --bg-base:      var(--neutral-100);
  --bg-surface:   #FFFFFF;
  --bg-elevated:  #FFFFFF;
  --bg-header:    #FFFFFF;
  --bg-input:     #FFFFFF;
  --bg-hover:     var(--neutral-100);
  --bg-active:    var(--neutral-200);
  --bg-selected:  var(--primary-50);
  --bg-disabled:  var(--neutral-200);

  --text-primary:     var(--neutral-900);
  --text-secondary:   var(--neutral-700);
  --text-tertiary:    var(--neutral-600);
  --text-placeholder: var(--neutral-500);
  --text-disabled:    var(--neutral-400);
  --text-brand:       var(--primary-700);
  --text-on-accent:   var(--neutral-950);
  --text-on-solid:    #FFFFFF;

  --border-divider: var(--neutral-200);
  --border-control: var(--neutral-500);
  --border-strong:  var(--neutral-700);
  --border-focus:   var(--primary-600);

  --accent-fill:          var(--primary-500);
  --accent-fill-hover:    var(--primary-600);
  --accent-fill-pressed:  var(--primary-700);
  --accent-subtle:        var(--primary-100);
  --accent-subtle-border: var(--primary-200);
  --accent-subtle-text:   var(--primary-800);

  --status-success-fg:     var(--success-700);
  --status-success-bg:     var(--success-50);
  --status-success-border: var(--success-200);
  --status-success-solid:  var(--success-600);

  --status-warning-fg:     var(--warning-700);
  --status-warning-bg:     var(--warning-50);
  --status-warning-border: var(--warning-200);
  --status-warning-solid:  var(--warning-500);

  --status-error-fg:     var(--error-700);
  --status-error-bg:     var(--error-50);
  --status-error-border: var(--error-200);
  --status-error-solid:  var(--error-600);

  --shadow-1: 0 1px 2px rgba(12,10,9,0.06), 0 1px 3px rgba(12,10,9,0.10);
  --shadow-2: 0 2px 4px rgba(12,10,9,0.06), 0 4px 8px rgba(12,10,9,0.08);
  --shadow-3: 0 4px 8px rgba(12,10,9,0.08), 0 12px 24px rgba(12,10,9,0.12);
  --shadow-4: 0 20px 40px rgba(12,10,9,0.16);
}
```

### 8.2 기본 패턴

테마 분기 없이 시맨틱 토큰만 참조한다.

```css
body {
  background: var(--bg-base);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 16px;
  line-height: 24px;
}

.card {
  background: var(--bg-surface);
  border: 1px solid var(--border-divider);
  box-shadow: var(--shadow-1);
  padding: 24px;                    /* unit-6 */
}

.btn-primary {
  background: var(--accent-fill);
  color: var(--text-on-accent);     /* White 금지: Primary-500 위 3.06:1 */
  border: none;
}
.btn-primary:hover  { background: var(--accent-fill-hover); }
.btn-primary:active { background: var(--accent-fill-pressed); color: var(--text-on-solid); }

.input {
  background: var(--bg-input);
  border: 1px solid var(--border-control);
  color: var(--text-primary);
}
.input::placeholder { color: var(--text-placeholder); }

:focus-visible {
  outline: 2px solid var(--border-focus);
  outline-offset: 2px;
}

.badge-error {
  background: var(--status-error-bg);
  color: var(--status-error-fg);
  border: 1px solid var(--status-error-border);
}
```

### 8.3 Tailwind 설정

```js
// tailwind.config.js
const px = n => `${n * 4}px`;

module.exports = {
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        primary: { 50:'#FFF6ED',100:'#FFEAD5',200:'#FED2AA',300:'#FDB274',400:'#FA863D',
                   500:'#F86517',600:'#F14D0D',700:'#C2360C',800:'#9A2C12',900:'#7C2612',950:'#431007' },
        neutral: { 50:'#FAFAF9',100:'#F5F5F4',200:'#E7E5E4',300:'#D6D3D1',400:'#A3A3A3',
                   500:'#78716C',600:'#57534E',700:'#44403C',800:'#292524',900:'#1C1917',950:'#0C0A09' },
        success: { 50:'#EFF6FF',100:'#DBEAFE',200:'#BFDBFE',300:'#93C5FD',400:'#60A5FA',
                   500:'#3B82F6',600:'#2563EB',700:'#1D4ED8',800:'#1E40AF',900:'#1E3A8A',950:'#172554' },
        warning: { 50:'#FEFCE8',100:'#FEF3C7',200:'#FDE68A',300:'#FCD34D',400:'#FBBF24',
                   500:'#F59E0B',600:'#D97706',700:'#B45309',800:'#92400E',900:'#78350F',950:'#451A03' },
        error:   { 50:'#FEF2F2',100:'#FEE2E2',200:'#FECACA',300:'#FCA5A5',400:'#F87171',
                   500:'#EF4444',600:'#DC2626',700:'#B91C1C',800:'#991B1B',900:'#7F1D1D',950:'#450A0A' },
        // 시맨틱 별칭 (테마 자동 전환)
        base:     'var(--bg-base)',
        surface:  'var(--bg-surface)',
        elevated: 'var(--bg-elevated)',
        accent:   'var(--accent-fill)',
      },
      textColor: {
        DEFAULT:     'var(--text-primary)',
        secondary:   'var(--text-secondary)',
        tertiary:    'var(--text-tertiary)',
        brand:       'var(--text-brand)',
        'on-accent': 'var(--text-on-accent)',
      },
      borderColor: {
        DEFAULT: 'var(--border-divider)',
        control: 'var(--border-control)',
        strong:  'var(--border-strong)',
        focus:   'var(--border-focus)',
      },
      boxShadow: {
        1: 'var(--shadow-1)', 2: 'var(--shadow-2)',
        3: 'var(--shadow-3)', 4: 'var(--shadow-4)',
      },
      fontFamily: {
        sans: ['"Pretendard Variable"', 'Pretendard', '-apple-system', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        xs:['12px',{lineHeight:'16px'}],    sm:['14px',{lineHeight:'20px'}],
        base:['16px',{lineHeight:'24px'}],  lg:['18px',{lineHeight:'28px'}],
        xl:['20px',{lineHeight:'28px'}],    '2xl':['24px',{lineHeight:'32px'}],
        '3xl':['30px',{lineHeight:'36px'}], '4xl':['36px',{lineHeight:'40px'}],
        '5xl':['48px',{lineHeight:'48px'}], '6xl':['60px',{lineHeight:'60px'}],
        '7xl':['72px',{lineHeight:'72px'}], '8xl':['96px',{lineHeight:'96px'}],
        '9xl':['128px',{lineHeight:'128px'}],
      },
      spacing: Object.fromEntries(
        [0.5,1,1.5,2,2.5,3,3.5,4,4.5,5,6,7,8,9,10,12,14,16,18,20,24,28,32,36,40,48,56,60,64,
         72,80,96,112,128,144,160,192,224,256,288,320,384,448,512,576,640]
          .map(n => [String(n), n === 0.5 ? '2px' : px(n)])
      ),
    },
  },
};
```

폰트 로딩: `https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/variable/pretendardvariable.css`

---

## 9. 검수 체크리스트

두 테마 각각에서 확인한다.

- [ ] 본문 텍스트가 배경 대비 4.5:1 이상인가
- [ ] 조작 가능한 컨트롤의 경계가 3:1 이상인가
- [ ] 라이트 모드에서 Primary-500이 텍스트나 얇은 선으로 쓰인 곳이 없는가
- [ ] Accent 채움 버튼의 라벨이 Neutral-950인가
- [ ] 라이트 모드에서 그림자·경계선 없이 놓인 흰 면이 없는가
- [ ] 다크 모드에서 인접한 면끼리 `border-divider`로 구분되는가
- [ ] 상태가 색상 단독으로 전달되는 곳이 없는가 (아이콘·레이블 병기)
- [ ] Accent 면적이 화면의 10%를 넘지 않는가
- [ ] 간격과 크기가 모두 4px 단위 스케일 값인가
- [ ] 포커스 링이 모든 대화형 요소에서 보이는가
- [ ] 테마 전환 시 컴포넌트 코드에 분기가 들어가지 않았는가
- [ ] 하드코딩된 HEX 값이 코드에 남아 있지 않은가
