---
name: Folio
description: 빨리 적고 바로 다시 찾는 차분한 문서 작업 공간
colors:
  ink: "#252522"
  muted-ink: "#686862"
  paper: "#fbfbf8"
  quiet-surface: "#f3f3ef"
  line: "#deded7"
  focus: "#5b57c8"
typography:
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.65
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 600
    lineHeight: 1.4
rounded:
  sm: "6px"
  md: "10px"
spacing:
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  search-trigger:
    backgroundColor: "{colors.quiet-surface}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "9px 12px"
---

# Design System: Folio

## 1. Overview

**Creative North Star: "조용한 책상"**

Folio는 종이와 검색창만 남은 정돈된 책상처럼 느껴져야 한다. Notion의 익숙한 조작 위치와
Obsidian의 문서 중심성을 가져오되, 장식보다 읽고 찾고 쓰는 흐름을 앞세운다.

**Key Characteristics:** 차분한 중성색, 한 가지 보라색 포커스, 넉넉한 본문 호흡, 예측 가능한 조작.

## 2. Colors

따뜻하게 기운 종이색 중성 팔레트에 포커스와 현재 선택에만 보라색을 쓴다.

**The One Accent Rule.** 포커스 색은 현재 선택, 주요 행동, 키보드 포커스에만 사용한다.

## 3. Typography

**Display Font:** system-ui
**Body Font:** system-ui

본문은 16px, 1.65 줄높이와 최대 72ch를 기본으로 한다. UI 라벨은 14px, 600 굵기로
문서 내용과 분명히 구분한다.

## 4. Elevation

기본 화면은 평평하다. 경계와 배경 명도 차이로 층을 나누고, 떠 있는 검색 결과와 메뉴에만
낮고 넓은 그림자를 쓴다.

## 5. Components

### Buttons

버튼은 표준 모양과 명확한 포커스를 쓴다. 아이콘만 있는 버튼에는 한국어 접근성 이름을 붙인다.

### Inputs / Fields

검색은 둥근 사각형 한 개로 보이며 검색 목적, 단축키, 현재 범위를 함께 알려준다.

### Navigation

읽기와 편집 모두 상단에서 Folio 이름, 검색, 현재 문서 행동 순서를 공유한다. 모바일에서는
텍스트를 줄여도 검색 입구를 숨기지 않는다.

## 6. Do's and Don'ts

### Do:

- **Do** 첫 화면과 모바일에 검색 입구를 항상 보여준다.
- **Do** 포커스 링과 최소 40px 터치 높이를 유지한다.
- **Do** 읽기와 편집에서 같은 행동에 같은 한국어 이름을 쓴다.

### Don't:

- **Don't** 핵심 행동을 hover나 키보드 단축키에만 둔다.
- **Don't** 기능을 아이콘 속에 숨기는 화면, 장식적인 대시보드, 과한 카드와 그라데이션을 만든다.
- **Don't** 읽기와 편집이 서로 다른 제품처럼 보이게 한다.
