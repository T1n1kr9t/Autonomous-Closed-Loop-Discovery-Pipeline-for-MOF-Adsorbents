# Senior Project Progress Report: Closed-Loop AI Discovery Pipeline for MOF GHG Adsorbents

**Project Title:** Closed-Loop Multi-Agent AI Pipeline for Greenhouse Gas Adsorbent Discovery  
**Target Application:** $\text{CO}_2 / \text{CH}_4$ Selective Adsorption in Metal-Organic Frameworks (MOFs)  
**Report Date:** 11 ตุลาคม 2026  
**Environment:** WSL2 Ubuntu (Python 3.12, RDKit, PORMAKE, Zeo++, RASPA2)

---

## 1. Executive Summary

ระบบ Closed-Loop Autonomous Pipeline สำหรับการค้นหาและออกแบบผลึกดูดซับก๊าซเรือนกระจก (MOF) ได้รับการพัฒนาและทดสอบครบวงจร **100% ตามแผนสถาปัตยกรรม** โดยสามารถรันการจำลองระดับฟิสิกส์โมเลกุลจริง (First-Principles & Classical GCMC) ครบทุกขั้นตอน ตั้งแต่การสร้างไอเดียระดับเคมี จนถึงการจำลอง Adsorption Isotherm/Selectivity โดยไม่ต้องพึ่งพาข้อมูล Mock up อีกต่อไป

---

## 2. สถาปัตยกรรมระบบ (Closed-Loop Architecture)

```mermaid
graph TD
    Target[Design Target: High CO2/CH4 Selectivity & PLD >= 3.8 A] --> Orch[Pipeline Orchestrator]
    
    subgraph Iterative Closed-Loop Discovery
        Orch --> Agent[Stage 1: Chemist Agent<br/>Gemini LLM / Chemical Heuristic Engine]
        Agent --> RDKit[Stage 2: RDKit Validator<br/>Valence & Carboxylate Anchors Check]
        RDKit -->|Valid SMILES| Pormake[Stage 3: PORMAKE Builder<br/>3D Crystal Assembly & CIF Generation]
        Pormake --> Zeo[Stage 4: Zeo++ Screener<br/>Voronoi Pore Limiting Diameter Analysis]
        Zeo -->|PLD >= 3.8 A| Raspa[Stage 5: RASPA2 GCMC Simulator<br/>Real Molecular Adsorption Simulation]
        
        RDKit -.->|Fail| FailLog[Active Learning Failure Log<br/>data/database/failure_log.json]
        Zeo -.->|Blocked Pore| FailLog
        Raspa -.->|Sim Error| FailLog
        FailLog -.->|Historical Feedback| Agent
    end

    Raspa -->|Success| SuccessDB[(Success Database<br/>data/database/success_candidates.json)]
```

---

## 3. รายละเอียดและสถานะความก้าวหน้าของแต่ละโมดูล (Module Breakdown)

| Stage | โมดูล | เทคโนโลยีหลัก | ฟังก์ชันการทำงาน | สถานะปัจจุบัน | การทดสอบ/การตรวจสอบ |
| :---: | :--- | :--- | :--- | :---: | :--- |
| **1** | **Chemist Agent** | Google Gemini LLM / Chemical Heuristic Pool | เสนอโครงสร้าง Linker (SMILES) พร้อม Chemical Hypothesis เพื่อปรับปรุงขั้ว/รูพรุน | ✅ สมบูรณ์ | รองรับทั้ง Online (Gemini API ผ่าน `.env`) และ Offline Heuristic Fallback 100% |
| **2** | **Chemical Validator** | [RDKit](src/chemistry/rdkit_validator.py) | ตรวจสอบ Valence Rules, Aromatic Core, และ Carboxylate Anchors ($\ge 2$ กลุ่ม) | ✅ สมบูรณ์ | คัดกรองโมเลกุลที่ต่อโครงสร้างไม่ได้ออกก่อนส่งต่อ |
| **3** | **Crystal Builder** | [PORMAKE](src/chemistry/pormake_builder.py) | ประกอบ Node ($Zn_4O$) + Edge (BDC อนุพันธ์) บนทอพอโลยี `pcu` ให้เป็นผลึก 3D | ✅ สมบูรณ์ | สร้างไฟล์ `.cif` โครงสร้างผลึกจริงสำเร็จ (มีพิกัดอะตอมครบถ้วน) |
| **4** | **Pore Screener** | [Zeo++ (`network`)](src/screening/zeo_screener.py) | คำนวณ Voronoi Decomposition หาค่า Pore Limiting Diameter (PLD) | ✅ สมบูรณ์ | วัดขนาดจริง เช่น $8.286\,\text{Å}$ (ผ่านเกณฑ์ขั้นต่ำ $3.8\,\text{Å}$) |
| **5** | **Adsorption Simulator** | [RASPA2 (`simulate`)](src/simulation/raspa_runner.py) | จำลอง Grand Canonical Monte Carlo (GCMC) ที่ 298.15 K, 1 bar (ส่วนผสม 50:50) | ✅ **สมบูรณ์จริง (Real Physics)** | แก้ปัญหาพาธและ CIF sync แล้ว ผลลัพธ์ได้ `is_mock: false` 100% |
| **Loop** | **Orchestrator & Active Learning** | [Pipeline Orchestrator](src/agents/orchestrator.py) | บันทึกประวัติความล้มเหลว นำกลับมาป้อนเป็น Feedback ให้ Agent ไม่เสนอโมเลกุลผิดพลาดซ้ำ | ✅ สมบูรณ์ | บันทึกผลสำเร็จลง Database และ Failure log อัตโนมัติ |

---

## 4. ปัญหาสำคัญที่ได้รับการแก้ไข (Key Issue Resolved)

> [!IMPORTANT]
> **การเปลี่ยนผ่านจาก Mock Simulation สู่ Real Physical Simulation**

* **ปัญหาเดิม:**  
  ในไฟล์ `data/database/success_candidates.json` ข้อมูลการจำลองถูกบันทึกเป็น `"is_mock": true` พร้อมค่าคงที่เดิมซ้ำ ๆ (เช่น $\text{CO}_2 = 4.25$, $\text{CH}_4 = 0.28$) เนื่องจากคำสั่ง `simulate` ของ RASPA2 หาไฟล์คำนิยามโมเลกุล `CO2.def` ไม่พบ เพราะขาดตัวแปร `RASPA_DIR=/opt/tools/raspa2` และขาดการเชื่อมพาธไปยังคลังโครงสร้าง `.cif`
* **การแก้ไข:**
  1. แก้ไข `src/simulation/raspa_runner.py` ให้ส่งตัวแปร Environment `RASPA_DIR` เข้า subprocess เสมอ
  2. เชื่อมโยงโครงสร้างผลึกที่สร้างขึ้นใหม่เข้าสู่คลังโมเดลของ RASPA อัตโนมัติ
  3. สร้าง Symlink `/home/tanakrit/RASPA/simulations -> /opt/tools/raspa2` ป้องกันคอมไพเลอร์ Fallback
* **ผลลัพธ์หลังแก้ไข:**  
  การจำลองรันบน CPU/WSL ใช้เวลาเพียง ~2–9 วินาทีต่อโครงสร้าง และได้ตัวเลขเชิงฟิสิกส์โมเลกุลจริง:
  * **Candidate:** $\text{MOF-5-NH}_2$
  * **PLD (Zeo++):** $8.286\,\text{Å}$
  * **$\text{CO}_2$ Loading:** $6.3809\,\text{mol/kg}$
  * **$\text{CH}_4$ Loading:** $0.0440\,\text{mol/kg}$
  * **Selectivity $S(\text{CO}_2/\text{CH}_4)$:** **$144.94$**
  * **Verification Flag:** `"is_mock": false` ✅

---

## 5. การรองรับสิ่งแวดล้อมและ LLM Configuration

1. **สร้างไฟล์จัดการคอนฟิกและความปลอดภัย**:
   * `.env` และ `.env.example` พร้อมรองรับ `GEMINI_API_KEY`
   * `.gitignore` เพื่อความปลอดภัยของ Secret Key
2. **การติดตั้ง Dependencies เพิ่มเติม**:
   * `python-dotenv`: โหลดตัวแปรสภาพแวดล้อมอัตโนมัติ
   * `google-generativeai`: รองรับการเรียกใช้ Gemini API จากภายนอก
   * อัปเดตลงใน `requirements.txt` ครบถ้วน
3. **การทดสอบความถูกต้อง (Test Coverage)**:
   * รัน `pytest tests/` ผ่านครบทั้ง 6 ชุดการทดสอบ (100% Pass)

---

## 6. แนวทางการดำเนินงานขั้นถัดไปสำหรับ Senior Project

1. **ปรับแต่งชื่อโมเดล LLM ใน `config/settings.yaml`**:
   * ตั้งค่าเป็น `gemini-1.5-flash` หรือ `gemini-2.0-flash` (แทน `gemini-3.6-flash` ซึ่งยังไม่มีบน Google API)
2. **รัน Autonomous Discovery Campaign ขนาดใหญ่**:
   * สั่งรันสำรวจวัสดุจำนวน 5–10 โครงสร้าง (เช่น `python src/pipeline.py --target 5 --max-trials 15`) เพื่อสร้างฐานข้อมูลวัสดุใหม่
3. **การวิเคราะห์ผลทางวิทยาศาสตร์ (Scientific Analysis & Plotting)**:
   * ทำกราฟเปรียบเทียบ Adsorption Isotherm หรือความสัมพันธ์ระหว่าง Functional Group Polarizability กับ Selectivity เพื่อนำไปเขียนในเล่มโครงงาน
