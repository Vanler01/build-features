# แผนพัฒนาต่อ + Multi-Agent Workflow — build-features

> เอกสารนี้คือ **สเปคที่ Opus ออกแบบไว้ให้ Sonnet ลงมือทำ**
> วิธีใช้: เปิด Claude Code ใน `~/build-features/` → เข้า plan mode → ให้ Opus อ่านไฟล์นี้ → delegate งานทีละเฟสให้ Sonnet
> อ้างอิงผลิตภัณฑ์: ข้อมูล Claude Code / Cowork ตรวจสอบ ณ มิ.ย. 2026

---

## 0. สรุปการประเมินสถานะปัจจุบัน

| ด้าน | สถานะ | สิ่งที่ต้องทำก่อนเพิ่มฟีเจอร์ |
|---|---|---|
| โครงสร้าง repo | ✅ monorepo + 2 submodule พร้อม | — |
| Docs (CLAUDE/AGENTS) | ⚠️ รวมไว้ไฟล์เดียว context ปนกัน | **แยกต่อโปรแกรม (เฟส 1)** |
| Bug ค้าง | ❌ 10 ตัว (BUG-1..10) | จัดเป็น backlog (เฟส 3) |
| Test coverage | ⚠️ ขาด overlay.py, main.py, auto_start (BUG-4) | เติมก่อนแตะ logic เดิม |
| Agent setup | ❌ ยังไม่มี `.claude/agents/` จริง | **สร้าง (เฟส 2)** |
| Permission | ❌ ยังกดอนุมัติทุกครั้ง | **ตั้ง settings.json (เฟส 2)** |

ข้อสรุป: **อย่าเพิ่งเพิ่มฟีเจอร์/โปรแกรมที่ 3** จนกว่าจะทำเฟส 1–2 เสร็จ ไม่งั้น context จะปนกันและ Sonnet จะหลงทาง

---

## 1. ภาพรวม Full-Circle Workflow (ใครทำอะไร)

```
        ┌─────────────── คุณ (Vanler) ───────────────┐
        │  ตั้งเป้า + อนุมัติ plan + กด merge เท่านั้น   │
        └───────────────────┬─────────────────────────┘
                            │
        ┌───────────────────▼─────────────────────────┐
        │  OPUS = Orchestrator (Code tab / CLI)         │
        │  - อ่าน BUILD_PLAN.md + Program_Report        │
        │  - แตกงานเป็น plan.md (Shift+Tab×2)           │
        │  - delegate ไปยัง subagents (ไม่เขียนโค้ดเอง)  │
        └───────────────────┬─────────────────────────┘
                            │ Task tool (model: sonnet)
        ┌───────────────────▼─────────────────────────┐
        │  SONNET subagents = คนลงมือ                   │
        │  planner · tdd-guide · code-reviewer ·        │
        │  security-reviewer · build-error-resolver ·   │
        │  macos-api-specialist · thai-lang-validator · │
        │  num-converter-validator                      │
        └───────────────────┬─────────────────────────┘
                            │ ผลลัพธ์ (commit + PR)
        ┌───────────────────▼─────────────────────────┐
        │  COWORK (Chat/Cowork tab) = งานรอบนอกโค้ด     │
        │  - อัปเดต Program_Report.txt หลัง merge       │
        │  - จัด GitHub (issues/release notes) ผ่าน      │
        │    Claude in Chrome connector                 │
        │  - เขียน changelog / README                   │
        └───────────────────────────────────────────────┘
```

**กฎแบ่งงาน Code ↔ Cowork** (ตาม docs ทางการ):
- **Code tab/CLI**: แก้บั๊ก, เพิ่มฟีเจอร์, รัน test, เปิด PR, จัดการ submodule → งานที่แตะโค้ด
- **Cowork tab**: research, แก้เอกสาร, สรุปรายงาน, จัดไฟล์, งานผ่าน browser → งานที่ **ไม่** แตะโค้ด
- **Dispatch** (จากมือถือ): สั่งเริ่ม session ทิ้งไว้ เช่น "เช้านี้รัน test ทั้ง 2 โปรแกรมแล้วสรุปให้"

---

## 2. ไฟล์ที่ต้องเพิ่ม / ปรับ (ตอบ "ต้องการไฟล์อะไรเพิ่ม")

โครงสร้างเป้าหมาย (ทำตามข้อเสนอแนะข้อ 7 ของ Program Report):

```
build-features/
├── CLAUDE.md              ← ปรับ: เหลือแค่ overview + @AGENTS.md (<100 บรรทัด)
├── AGENTS.md              ← ปรับ: เหลือเฉพาะ "ของร่วม" (stack, security, git submodule, shared arch)
├── BUILD_PLAN.md          ← ใหม่: ไฟล์นี้ (สเปคงาน)
│
├── .claude/
│   ├── settings.json      ← ใหม่: permission allow/deny + acceptEdits (ดูข้อ 3)
│   └── agents/            ← ใหม่: subagent ทั้งหมด (ดูข้อ 4)
│       ├── planner.md
│       ├── code-reviewer.md
│       ├── security-reviewer.md
│       ├── build-error-resolver.md
│       ├── tdd-guide.md
│       ├── macos-api-specialist.md
│       ├── thai-lang-validator.md
│       └── num-converter-validator.md
│
├── en-th-word-swap/
│   ├── CLAUDE.md          ← ใหม่: rules เฉพาะ en-th (keyboard_map, PyThaiNLP, UserTracker)
│   └── AGENTS.md          ← ใหม่: thai-lang-validator trigger, test rules, file ownership ของ en-th
│
└── num-to-text/
    ├── CLAUDE.md          ← ใหม่: rules เฉพาะ num (converter, languages, financial mode)
    └── AGENTS.md          ← ใหม่: num-converter-validator trigger, test rules, file ownership ของ num
```

หลักการ "closer file overrides parent" — ตอนทำงานใน `en-th-word-swap/` Claude Code จะโหลด CLAUDE.md ของ root **และ** ของ submodule ทับลงมา → context ตรงเป้าไม่ปนกับ num-to-text

**สิ่งที่ย้ายลง per-project CLAUDE.md:**
- en-th: กฎ keyboard_map.py, การใช้ PyThaiNLP, Direction A/B logic, UserTracker
- num: กฎ converter.py, อัลกอริทึม Thai/JA/ZH ที่เขียนเอง, language detection

**สิ่งที่เก็บไว้ root (ของร่วม):** Python 3.10+/PyObjC/macOS 12+, **ห้าม log keystroke**, git submodule workflow, CGEventTap/NSPanel patterns

---

## 3. ตั้ง Permission ให้ไม่ต้องกดอนุมัติบ่อย (ตอบหัวข้อหลัก)

Claude Code เช็ค permission ตามลำดับ **deny → ask → allow** (rule แรกที่ match ชนะ) ตั้งใน `.claude/settings.json`:

```jsonc
{
  "permissions": {
    "defaultMode": "acceptEdits",          // auto-รับ file edit ในโฟลเดอร์โปรเจกต์
    "allow": [
      "Read(**)",
      "Grep(**)",
      "Glob(**)",
      "Edit(en-th-word-swap/**)",
      "Edit(num-to-text/**)",
      "Write(en-th-word-swap/**)",
      "Write(num-to-text/**)",
      "Bash(python3 -m pytest *)",
      "Bash(ruff check *)",
      "Bash(ruff:*)",
      "Bash(git status)",
      "Bash(git diff *)",
      "Bash(git add *)",
      "Bash(git commit *)",
      "Bash(git log *)",
      "Bash(python3 -c *)"
    ],
    "deny": [
      "Read(./**/cache/**)",               // กัน secret/keylog cache หลุดเข้า context
      "Write(**/cache/**)",
      "Bash(rm -rf *)",
      "Bash(git push *)",                  // push/merge ให้คุณกดเอง
      "Bash(sudo *)",
      "Bash(curl *)",
      "Bash(* install.sh)"                 // ห้ามรัน install ที่แตะ LaunchAgent อัตโนมัติ
    ],
    "ask": [
      "Bash(git checkout *)",
      "Bash(git reset *)"
    ]
  }
}
```

**โหมดที่เลือกได้** (`defaultMode`):
- `acceptEdits` ← **แนะนำ**: รับ edit อัตโนมัติ แต่ Bash/network ยังถาม → สมดุลระหว่างลื่นกับปลอดภัย
- `bypassPermissions` / CLI `--dangerously-skip-permissions` = ไม่ถามอะไรเลย ("YOLO") → ใช้เฉพาะใน sandbox เท่านั้น
- `dontAsk` = อนุมัติเฉพาะที่อยู่ใน allow ที่เหลือ **ปฏิเสธเงียบ ๆ** (locked-down agent)

**คำเตือนความปลอดภัย (สำคัญสำหรับโปรเจกต์นี้):**
1. โปรเจกต์นี้ hook keyboard ทั้งระบบ (CGEventTap) + แตะ Accessibility → **อย่าใช้ blanket `bypassPermissions` นอก sandbox** เด็ดขาด ความผิดพลาดอาจ inject/ดักคีย์โดยไม่ตั้งใจ
2. เปิด sandbox ด้วย `/sandbox` (macOS ใช้ Seatbelt ได้เลย) ถ้าอยากปล่อยรันยาว ๆ แบบไม่ถาม — sandbox เป็นกรอบความปลอดภัยแทน prompt
3. ใช้ `deny` กัน `cache/` ไม่ให้เข้า context (ตรงกับกฎ AGENTS.md เดิม "never commit keylog data")
4. ใช้ `.claude/settings.local.json` (gitignore อัตโนมัติ) สำหรับ allow-rule ส่วนตัว ไม่ต้อง commit ขึ้น repo

**ข้อจำกัดที่ควรรู้:** มีรายงานบั๊ก (issue #29026) ว่า **Claude Code เวอร์ชัน desktop app บน macOS อาจไม่อ่าน settings.json permission** ทำให้ยังถามทุกครั้ง — ถ้าเจออาการนี้ ให้รันผ่าน **CLI** (`claude`) ซึ่งเคารพ settings.json แน่นอน หรือเปิด toggle "Allow bypass permissions mode" ใน Settings ของ Code tab

---

## 4. Agent Roster (Opus ออกแบบ / Sonnet ทำ)

จำนวน agent ตามขนาดงาน (อย่า spawn เกินจำเป็น — anti-pattern):

| ขนาดงาน | subagents | ตัวอย่างในโปรเจกต์นี้ |
|---|---|---|
| typo / 1 ไฟล์ | 0 (main session) | แก้ docstring |
| 2–5 ไฟล์ | 2–3 | BUG-5 (overlay+main), BUG-1 |
| ข้ามทั้ง 2 โปรแกรม | 3–5 fan-out | refactor settings.py ให้เหมือนกัน |

**Model tiering:** ตั้ง `CLAUDE_CODE_SUBAGENT_MODEL=claude-sonnet-4-6` หรือใช้ `/model opusplan` (Opus วาง, Sonnet ทำ) — ประหยัด token 5–10× โดยคุณภาพไม่ตก

**Roster 8 ตัว** (สร้างด้วย `/agents` → "Generate with Claude" แล้วปรับ):

| agent | model | tools | เรียกเมื่อ |
|---|---|---|---|
| `planner` | opus | Read, Grep, Glob | เริ่มทุกฟีเจอร์ที่แตะ ≥3 ไฟล์ |
| `tdd-guide` | sonnet | Read, Edit, Write, Bash | เขียน failing test ก่อน implement |
| `code-reviewer` | sonnet | Read, Grep, Glob, Bash | **หลังแก้โค้ดทันที** |
| `security-reviewer` | sonnet | Read, Grep, Glob, Bash | **ก่อน merge เข้า main เสมอ** |
| `build-error-resolver` | sonnet | Read, Edit, Bash | ทันทีที่เจอ ImportError/AttributeError |
| `macos-api-specialist` | sonnet | Read, Edit, Grep | แตะ CGEventTap / NSPanel |
| `thai-lang-validator` | sonnet | Read, Grep | ก่อนแก้ keyboard_map.py |
| `num-converter-validator` | sonnet | Read, Grep, Bash | ก่อนแก้ converter.py / Thai-JA-ZH algo |

**Template subagent** (ตัวอย่าง code-reviewer — copy ไปปรับได้):

```markdown
---
name: code-reviewer
description: Reviews code for quality, security, and style. Use PROACTIVELY immediately after writing or modifying code. MUST BE USED before any merge to main.
tools: Read, Grep, Glob, Bash
model: sonnet
---
You are a senior reviewer for a macOS Python daemon project.

When invoked:
1. Run `git diff` to find changed files
2. Check each: edge cases, specific-exception handling (no bare except),
   type hints, 100-char line limit, %-formatting in logs (not f-strings),
   docstrings on public functions
3. SECURITY: confirm NO raw keystrokes are logged anywhere
4. Confirm CGEventTap is mocked in tests (never real in CI)

Output: CRITICAL / HIGH / MEDIUM / LOW. Report only — do not modify files.
```

**กฎทอง pass context ไม่ใช่แค่ query** — เวลา Opus สั่ง subagent ต้องบอก *เหตุผล/เป้าหมาย* ด้วย ไม่ใช่แค่คำสั่งสั้น ๆ (subagent เห็นแค่สิ่งที่ส่งให้ ไม่เห็น context รวม)

---

## 5. Per-Feature Loop (รอบการทำงาน 1 ฟีเจอร์/บั๊ก)

ทำตาม 4-phase ของ Anthropic: **Explore → Plan → Implement → Commit**

```
1. EXPLORE   (Opus, plan mode / Shift+Tab×2, read-only)
   "อ่าน <project>/main.py + เข้าใจ state machine ส่วนที่เกี่ยว"

2. PLAN      (Opus → planner subagent)
   ขอ plan.md → กด Ctrl+G เปิดใน editor แก้เอง → คุณ approve
   ▸ one-sentence rule: ถ้าอธิบาย diff ได้ใน 1 ประโยค = ข้าม plan
   ▸ ถ้า plan แตะ >7 ไฟล์ = แตกเป็น plan ย่อย

3. IMPLEMENT (Opus delegate ไป Sonnet subagents)
   ▸ tdd-guide: เขียน test ที่ fail ก่อน
   ▸ domain agent ที่เกี่ยว (macos-api / thai-lang / num-converter)
   ▸ build-error-resolver: ทันทีถ้า import พัง
   ▸ code-reviewer: หลังแก้เสร็จ (PostToolUse hook ก็ได้)

4. COMMIT    (security-reviewer ก่อน → คุณกด merge)
   ▸ security-reviewer ผ่าน → conventional commit (feat:/fix:/...)
   ▸ git push + merge = คุณกดเอง (อยู่ใน deny/ask)
   ▸ Cowork อัปเดต Program_Report.txt + changelog
```

---

## 6. Roadmap แนะนำ (ลำดับก่อนหลัง)

**เฟส 1 — แยกเอกสาร (ทำก่อนสุด, ~1 session)**
- แตก CLAUDE.md/AGENTS.md root → per-project ตามข้อ 2
- งานนี้ Sonnet ทำได้ตรง ๆ ไม่ต้อง subagent เยอะ

**เฟส 2 — ตั้ง agent + permission infra (~1 session)**
- สร้าง `.claude/settings.json` (ข้อ 3) + `.claude/agents/*.md` (ข้อ 4)
- ตั้ง `CLAUDE_CODE_SUBAGENT_MODEL` / `/model opusplan`

**เฟส 3 — เคลียร์บั๊กค้างเป็น backlog** (เรียงตามความเสี่ยง)
- 🔴 BUG-1 (password field ใน terminal) — ความเสี่ยงความปลอดภัยสูงสุด → security-reviewer + macos-api-specialist
- 🔴 BUG-5 (คลิก overlay ไม่ inject) — UX เสีย, แก้ตรงไปตรงมา
- 🟡 BUG-4 (test auto_start ขาด) — เติม test กัน regression
- 🟡 BUG-6 (NumberOverlay สร้างใหม่ทุกครั้ง) — perf
- 🟢 BUG-2,3,7,8,9,10 — จัดทีหลังตามว่าง

**เฟส 4 — เพิ่มฟีเจอร์ใหม่ / โปรแกรมที่ 3**
- ทำได้ก็ต่อเมื่อเฟส 1–2 เสร็จ (โครง doc/agent รองรับการ scale แล้ว)
- โปรแกรมที่ 3 = เพิ่ม submodule + โฟลเดอร์ + CLAUDE/AGENTS ของตัวเอง ตาม pattern เดิม

---

## 7. Caveats (อ่านก่อนเริ่ม)

1. **Multi-agent กิน token ~15× ของ chat ปกติ** — คุ้มเฉพาะงานที่แตกขนานได้จริง งานเล็ก (<3 ไฟล์) ให้ใช้ main session เปล่า ๆ ดีกว่า
2. ตัวเลข "ดีกว่า 90.2%" ของ Anthropic มาจาก eval งาน **research** ไม่ใช่ coding — งานโค้ดได้ผลน้อยกว่า เพราะ task ขนานกันได้น้อยกว่า
3. **Plan mode มี overhead** — งานที่ scope ชัดอยู่แล้ว สั่งทำตรง ๆ เร็วกว่า
4. **bypassPermissions บนโปรเจกต์ keyboard-hook = อันตราย** — ยึด acceptEdits + allow-list + sandbox แทน
5. Cowork/computer use ยังเป็น research preview และจะ **ขอ permission ก่อนแตะแต่ละแอป** — "full circle" ฝั่ง Cowork จึงยังไม่ใช่ 100% ไร้การกดอนุมัติ (ตรงนี้เป็นข้อจำกัดด้านความปลอดภัยโดยตั้งใจ)
6. ห้ามให้ subagent สร้าง subagent ซ้อน (no nesting) และ cap = 10 ตัวพร้อมกัน

---

## 8. คำสั่งเริ่มต้น (Day 1)

```bash
# ใน ~/build-features/
claude                              # เปิด CLI (เคารพ settings.json แน่นอน)
/init                               # ถ้ายังไม่มี CLAUDE.md
/agents                             # สร้าง subagent (Generate with Claude)
export CLAUDE_CODE_SUBAGENT_MODEL=claude-sonnet-4-6
/model opusplan                     # Opus วาง, Sonnet ทำ
/sandbox                            # เปิด sandbox (Seatbelt) ก่อนรันยาว ๆ
# จากนั้น: "อ่าน BUILD_PLAN.md แล้วเริ่มเฟส 1"
```
