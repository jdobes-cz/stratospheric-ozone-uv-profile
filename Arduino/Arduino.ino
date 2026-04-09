// UV + Atmospheric Pressure + Ozone + RTC + EEPROM + microSD data logger
// Arduino Pro Mini (ATmega328PB, 3.3V/8MHz)
// LTR390 (0x53) + MS5607 (0x76) + SEN0321 (0x73) + DS3231 (0x68) + AT24C256 (0x50) over shared I2C
// LaskaKit microSD module on SPI (CS = D10)
//
// Data is written to EEPROM (every 30s) and microSD (every 10s) on separate intervals.
// microSD stores human-readable CSV files named by date (e.g. 20260325.CSV).
//
// Serial commands:
//   record <seconds>  - start recording (seconds sets SD interval, EEPROM fixed at 30s)
//   stop              - stop recording
//   dump              - dump all EEPROM records as CSV
//   dumpsd            - dump current day's SD file over serial
//   status            - show EEPROM + SD usage
//   clear             - erase all EEPROM records
//   settime YYYY MM DD HH MM SS - set RTC time
//
// Sensor flags (sensor_flags column in CSV/EEPROM):
//   bit 0 (0x01) - UVS: LTR390 UV data valid
//   bit 1 (0x02) - ALS: LTR390 ambient light data valid
//   bit 2 (0x04) - MS5607: pressure/temperature data valid
//   bit 3 (0x08) - O3: ozone reading valid (>=0)
//   All OK = 15 (0x0F)

#include <Wire.h>
#include <SPI.h>
#include <SD.h>
#include <LTR390.h>
#include <MS5611.h>
#include <DFRobot_OzoneSensor.h>
#include <RTClib.h>

#define COLLECT_NUMBER 20  // ozone averaging sample count (1-100)

// AT24C256 EEPROM config
#define EEPROM_ADDR       0x50
#define EEPROM_SIZE       32768UL  // 32KB
#define HEADER_SIZE       8        // 4 bytes record count + 4 bytes next write addr
#define RECORD_SIZE       35       // bytes per data record (34 data + 1 sensor flags)

#define MAX_RECORDS       ((EEPROM_SIZE - HEADER_SIZE) / RECORD_SIZE)
#define EEPROM_PAGE_SIZE  64

// Sensor status flag bits
#define FLAG_UVS_OK    0x01
#define FLAG_ALS_OK    0x02
#define FLAG_MS5607_OK 0x04
#define FLAG_O3_OK     0x08

// microSD config
#define SD_CS_PIN         10

// Serial command buffer
#define CMD_BUF_SIZE      48
char cmdBuf[CMD_BUF_SIZE];
uint8_t cmdIdx = 0;

LTR390 ltr390;
MS5607 ms5607(0x76);
DFRobot_OzoneSensor ozone;
RTC_DS3231 rtc;

bool ltr390Available = false;
bool ms5607Available = false;
bool ozoneAvailable = false;
bool rtcAvailable = false;
uint32_t bootTimeOffset = 0;  // random offset when RTC unavailable

bool recording = true; // recording by default
uint16_t recordInterval = 10;  // seconds between SD recordings
unsigned long lastRecordTime = 0;
uint16_t eepromInterval = 30;  // seconds between EEPROM recordings
unsigned long lastEepromTime = 0;
uint32_t recordCount = 0;
uint32_t nextWriteAddr = HEADER_SIZE;
bool sdAvailable = false;
uint8_t ltr390Fails = 0;
uint8_t ms5607Fails = 0;
uint8_t ozoneFails = 0;
#define SENSOR_REINIT_AFTER 3  // reinit after this many consecutive failures
unsigned long lastSDRetry = 0;
#define SD_RETRY_INTERVAL_MS 30000UL  // retry SD every 30 seconds

// --- AT24C256 low-level functions ---

void eepromWriteBlock(uint16_t addr, const uint8_t *data, uint8_t len) {
  while (len > 0) {
    uint8_t pageRemaining = EEPROM_PAGE_SIZE - (addr % EEPROM_PAGE_SIZE);
    uint8_t chunk = min(len, pageRemaining);
    chunk = min(chunk, (uint8_t)30);

    Wire.beginTransmission((uint8_t)EEPROM_ADDR);
    Wire.write((uint8_t)(addr >> 8));
    Wire.write((uint8_t)(addr & 0xFF));
    for (uint8_t i = 0; i < chunk; i++) {
      Wire.write(data[i]);
    }
    Wire.endTransmission();
    delay(5);

    addr += chunk;
    data += chunk;
    len -= chunk;
  }
}

void eepromReadBlock(uint16_t addr, uint8_t *data, uint8_t len) {
  while (len > 0) {
    uint8_t chunk = min(len, (uint8_t)30);

    Wire.beginTransmission((uint8_t)EEPROM_ADDR);
    Wire.write((uint8_t)(addr >> 8));
    Wire.write((uint8_t)(addr & 0xFF));
    Wire.endTransmission();

    Wire.requestFrom((uint8_t)EEPROM_ADDR, chunk);
    for (uint8_t i = 0; i < chunk && Wire.available(); i++) {
      data[i] = Wire.read();
    }

    addr += chunk;
    data += chunk;
    len -= chunk;
  }
}

// --- EEPROM header management ---

void writeHeader() {
  uint8_t buf[8];
  memcpy(buf, &recordCount, 4);
  memcpy(buf + 4, &nextWriteAddr, 4);
  eepromWriteBlock(0, buf, 8);
}

void readHeader() {
  uint8_t buf[8];
  eepromReadBlock(0, buf, 8);
  memcpy(&recordCount, buf, 4);
  memcpy(&nextWriteAddr, buf + 4, 4);

  if (recordCount > MAX_RECORDS || nextWriteAddr > EEPROM_SIZE) {
    recordCount = 0;
    nextWriteAddr = HEADER_SIZE;
    writeHeader();
  }
}

// --- Print a DateTime as YYYY/MM/DD HH:MM:SS ---

void printDateTime(Print &out, const DateTime &dt) {
  out.print(dt.year());
  out.print('/');
  if (dt.month() < 10) out.print('0');
  out.print(dt.month());
  out.print('/');
  if (dt.day() < 10) out.print('0');
  out.print(dt.day());
  out.print(' ');
  if (dt.hour() < 10) out.print('0');
  out.print(dt.hour());
  out.print(':');
  if (dt.minute() < 10) out.print('0');
  out.print(dt.minute());
  out.print(':');
  if (dt.second() < 10) out.print('0');
  out.print(dt.second());
}

// --- Build SD filename from DateTime: "YYYYMMDD.CSV" ---

void getSDFilename(const DateTime &dt, char *buf) {
  // Manual number-to-string to avoid sprintf format string in RAM
  uint16_t y = dt.year();
  buf[0] = '0' + (y / 1000);
  buf[1] = '0' + (y / 100 % 10);
  buf[2] = '0' + (y / 10 % 10);
  buf[3] = '0' + (y % 10);
  buf[4] = '0' + (dt.month() / 10);
  buf[5] = '0' + (dt.month() % 10);
  buf[6] = '0' + (dt.day() / 10);
  buf[7] = '0' + (dt.day() % 10);
  buf[8] = '.';
  buf[9] = 'C';
  buf[10] = 'S';
  buf[11] = 'V';
  buf[12] = '\0';
}

// --- SD card helpers ---

void sdWriteHeaderIfNew(const char *filename) {
  if (!sdAvailable) return;
  if (!SD.exists(filename)) {
    File f = SD.open(filename, FILE_WRITE);
    if (f) {
      f.println(F("timestamp,als,lux,uvs,uvi,temp_c,pressure_mbar,ozone_ppb,rtc_temp_c,sensor_flags"));
      f.close();
    }
  }
}

void sdWriteRecord(const DateTime &dt, uint32_t als, float lux,
                   uint32_t uvs, float uvi, float temperature,
                   float pressure, int16_t ozonePpb, float rtcTemp,
                   uint8_t sensorFlags) {
  if (!sdAvailable) {
    unsigned long now_ms = millis();
    if (now_ms - lastSDRetry >= SD_RETRY_INTERVAL_MS) {
      lastSDRetry = now_ms;
      if (SD.begin(SD_CS_PIN)) {
        sdAvailable = true;
        Serial.println(F("SD reconnected"));
      }
    }
    if (!sdAvailable) return;
  }

  char filename[13];
  getSDFilename(dt, filename);
  sdWriteHeaderIfNew(filename);

  File f = SD.open(filename, FILE_WRITE);
  if (f) {
    printDateTime(f, dt);
    f.print(',');
    f.print(als);
    f.print(',');
    f.print(lux, 2);
    f.print(',');
    f.print(uvs);
    f.print(',');
    f.print(uvi, 2);
    f.print(',');
    f.print(temperature, 2);
    f.print(',');
    f.print(pressure, 2);
    f.print(',');
    f.print(ozonePpb);
    f.print(',');
    f.print(rtcTemp, 2);
    f.print(',');
    f.println(sensorFlags);
    f.close();
  } else {
    Serial.println(F("SD write failed, reinit..."));
    sdAvailable = false;
    if (SD.begin(SD_CS_PIN)) {
      sdAvailable = true;
      Serial.println(F("SD recovered"));
    }
  }
}

// --- EEPROM record functions ---

bool writeRecord(uint32_t timestamp, uint32_t als, float lux,
                 uint32_t uvs, float uvi, float temperature,
                 float pressure, int16_t ozonePpb, float rtcTemp,
                 uint8_t sensorFlags) {
  if (recordCount >= MAX_RECORDS) {
    Serial.println(F("EEPROM full!"));
    return false;
  }

  uint8_t buf[RECORD_SIZE];
  uint8_t offset = 0;

  memcpy(buf + offset, &timestamp, 4);    offset += 4;
  memcpy(buf + offset, &als, 4);          offset += 4;
  memcpy(buf + offset, &lux, 4);          offset += 4;
  memcpy(buf + offset, &uvs, 4);          offset += 4;
  memcpy(buf + offset, &uvi, 4);          offset += 4;
  memcpy(buf + offset, &temperature, 4);  offset += 4;
  memcpy(buf + offset, &pressure, 4);     offset += 4;
  memcpy(buf + offset, &ozonePpb, 2);     offset += 2;
  memcpy(buf + offset, &rtcTemp, 4);      offset += 4;
  buf[offset] = sensorFlags;              offset += 1;

  eepromWriteBlock(nextWriteAddr, buf, RECORD_SIZE);

  nextWriteAddr += RECORD_SIZE;
  recordCount++;
  writeHeader();

  return true;
}

void dumpRecords() {
  if (recordCount == 0) {
    Serial.println(F("No EEPROM records stored."));
    return;
  }

  Serial.println(F("timestamp,als,lux,uvs,uvi,temp_c,pressure_mbar,ozone_ppb,rtc_temp_c,sensor_flags"));

  uint32_t addr = HEADER_SIZE;
  for (uint32_t i = 0; i < recordCount; i++) {
    uint8_t buf[RECORD_SIZE];
    eepromReadBlock(addr, buf, RECORD_SIZE);

    uint32_t timestamp, als, uvs;
    float lux, uvi, temperature, pressure, rtcTemp;
    int16_t ozonePpb;
    uint8_t sensorFlags;
    uint8_t offset = 0;

    memcpy(&timestamp, buf + offset, 4);    offset += 4;
    memcpy(&als, buf + offset, 4);          offset += 4;
    memcpy(&lux, buf + offset, 4);          offset += 4;
    memcpy(&uvs, buf + offset, 4);          offset += 4;
    memcpy(&uvi, buf + offset, 4);          offset += 4;
    memcpy(&temperature, buf + offset, 4);  offset += 4;
    memcpy(&pressure, buf + offset, 4);     offset += 4;
    memcpy(&ozonePpb, buf + offset, 2);     offset += 2;
    memcpy(&rtcTemp, buf + offset, 4);      offset += 4;
    sensorFlags = buf[offset];              offset += 1;

    DateTime dt(timestamp);
    printDateTime(Serial, dt);

    Serial.print(',');
    Serial.print(als);
    Serial.print(',');
    Serial.print(lux, 2);
    Serial.print(',');
    Serial.print(uvs);
    Serial.print(',');
    Serial.print(uvi, 2);
    Serial.print(',');
    Serial.print(temperature, 2);
    Serial.print(',');
    Serial.print(pressure, 2);
    Serial.print(',');
    Serial.print(ozonePpb);
    Serial.print(',');
    Serial.print(rtcTemp, 2);
    Serial.print(',');
    Serial.println(sensorFlags);

    addr += RECORD_SIZE;
  }

  Serial.print(F("Total: "));
  Serial.print(recordCount);
  Serial.println(F(" records"));
}

void dumpSDFile(const DateTime &dt) {
  if (!sdAvailable) {
    Serial.println(F("SD card not available."));
    return;
  }

  char filename[13];
  getSDFilename(dt, filename);

  if (!SD.exists(filename)) {
    Serial.print(F("File not found: "));
    Serial.println(filename);
    return;
  }

  Serial.print(F("--- "));
  Serial.print(filename);
  Serial.println(F(" ---"));

  File f = SD.open(filename, FILE_READ);
  if (f) {
    unsigned long sz = f.size();
    while (f.available()) {
      Serial.write(f.read());
    }
    f.close();
    Serial.print(F("--- end ("));
    Serial.print(sz);
    Serial.println(F(" bytes) ---"));
  } else {
    Serial.println(F("SD read failed!"));
  }
}

void clearRecords() {
  recordCount = 0;
  nextWriteAddr = HEADER_SIZE;
  writeHeader();
  Serial.println(F("EEPROM cleared."));
}

void printStatus() {
  Serial.println(F("== EEPROM =="));
  Serial.print(F("Records: "));
  Serial.print(recordCount);
  Serial.print(F(" / "));
  Serial.println(MAX_RECORDS);
  Serial.print(F("Used: "));
  Serial.print(nextWriteAddr);
  Serial.print(F(" / "));
  Serial.print(EEPROM_SIZE);
  Serial.println(F(" bytes"));

  Serial.println(F("== microSD =="));
  if (sdAvailable) {
    Serial.println(F("Status: OK"));
    DateTime now = rtc.now();
    char filename[13];
    getSDFilename(now, filename);
    if (SD.exists(filename)) {
      File f = SD.open(filename, FILE_READ);
      if (f) {
        Serial.print(F("Today ("));
        Serial.print(filename);
        Serial.print(F("): "));
        Serial.print(f.size());
        Serial.println(F(" bytes"));
        f.close();
      }
    } else {
      Serial.print(F("Today ("));
      Serial.print(filename);
      Serial.println(F("): no file yet"));
    }
  } else {
    Serial.println(F("Status: NOT AVAILABLE"));
  }

  Serial.print(F("Recording: "));
  Serial.println(recording ? F("ON") : F("OFF"));
  if (recording) {
    Serial.print(F("SD interval: "));
    Serial.print(recordInterval);
    Serial.print(F("s, EEPROM interval: "));
    Serial.print(eepromInterval);
    Serial.println('s');
  }
}

// --- Serial command parser (no String class - uses char buffer) ---

int parseIntAt(const char *buf, uint8_t *pos) {
  while (buf[*pos] == ' ') (*pos)++;
  int val = 0;
  while (buf[*pos] >= '0' && buf[*pos] <= '9') {
    val = val * 10 + (buf[*pos] - '0');
    (*pos)++;
  }
  return val;
}

void processCommand(const char *cmd) {
  while (*cmd == ' ') cmd++;

  if (strcmp_P(cmd, PSTR("record")) == 0 || strncmp_P(cmd, PSTR("record "), 7) == 0) {
    if (cmd[6] == ' ') {
      uint8_t pos = 7;
      int val = parseIntAt(cmd, &pos);
      if (val > 0) recordInterval = val;
    }
    recording = true;
    lastRecordTime = 0;
    lastEepromTime = 0;
    Serial.print(F("Recording started, SD: "));
    Serial.print(recordInterval);
    Serial.print(F("s, EEPROM: "));
    Serial.print(eepromInterval);
    Serial.println('s');
  }
  else if (strcmp_P(cmd, PSTR("stop")) == 0) {
    recording = false;
    Serial.println(F("Recording stopped."));
  }
  else if (strcmp_P(cmd, PSTR("dump")) == 0) {
    dumpRecords();
  }
  else if (strcmp_P(cmd, PSTR("dumpsd")) == 0 || strncmp_P(cmd, PSTR("dumpsd "), 7) == 0) {
    if (cmd[6] == ' ') {
      uint8_t pos = 7;
      int y = parseIntAt(cmd, &pos);
      int m = parseIntAt(cmd, &pos);
      int d = parseIntAt(cmd, &pos);
      DateTime dt(y, m, d, 0, 0, 0);
      dumpSDFile(dt);
    } else {
      DateTime now = rtc.now();
      dumpSDFile(now);
    }
  }
  else if (strcmp_P(cmd, PSTR("status")) == 0) {
    printStatus();
  }
  else if (strcmp_P(cmd, PSTR("clear")) == 0) {
    recording = false;
    clearRecords();
  }
  else if (strcmp_P(cmd, PSTR("settime")) == 0 || strncmp_P(cmd, PSTR("settime "), 8) == 0) {
    if (cmd[7] != ' ') {
      Serial.println(F("Usage: settime YYYY MM DD HH MM SS"));
    } else {
      uint8_t pos = 8;
      int parts[6];
      for (uint8_t i = 0; i < 6; i++) {
        parts[i] = parseIntAt(cmd, &pos);
      }
      if (parts[0] < 2000 || parts[0] > 2099 ||
          parts[1] < 1 || parts[1] > 12 ||
          parts[2] < 1 || parts[2] > 31 ||
          parts[3] > 23 || parts[4] > 59 || parts[5] > 59) {
        Serial.println(F("Invalid date/time!"));
      } else {
        rtc.adjust(DateTime(parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]));
        Serial.println(F("RTC time set."));
      }
    }
  }
  else if (strcmp_P(cmd, PSTR("help")) == 0) {
    Serial.println(F("Commands: record [sec], stop, dump, dumpsd [YYYY MM DD], status, clear, settime YYYY MM DD HH MM SS"));
  }
  else {
    Serial.print(F("Unknown: "));
    Serial.println(cmd);
    Serial.println(F("Type 'help' for commands"));
  }
}

// --- Setup & Loop ---

void setup() {
  Serial.begin(9600);

  Wire.begin();

  // Init LTR390
  if (ltr390.init()) {
    ltr390.setGain(LTR390_GAIN_3);
    ltr390.setResolution(LTR390_RESOLUTION_18BIT);
    ltr390.enable(true);
    ltr390Available = true;
    Serial.println(F("LTR390 ready"));
  } else {
    Serial.println(F("LTR390 not found - skipping"));
  }

  // Init MS5607
  if (ms5607.begin()) {
    ms5607.setOversampling(OSR_ULTRA_HIGH);
    ms5607Available = true;
    Serial.println(F("MS5607 ready"));
  } else {
    Serial.println(F("MS5607 not found - skipping"));
  }

  // Init SEN0321 ozone sensor
  if (ozone.begin(OZONE_ADDRESS_3)) {
    ozone.setModes(MEASURE_MODE_PASSIVE);
    ozoneAvailable = true;
    Serial.println(F("SEN0321 ready"));
  } else {
    Serial.println(F("SEN0321 not found - skipping"));
  }

  // Init DS3231 RTC
  if (rtc.begin()) {
    rtcAvailable = true;
    Serial.println(F("DS3231 ready"));
    if (rtc.lostPower()) {
      Serial.println(F("RTC lost power, setting compile time..."));
      rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));
    }
  } else {
    // Random offset so each power-up has distinct timestamps
    randomSeed(analogRead(A0) ^ analogRead(A1) ^ micros());
    bootTimeOffset = random(100000UL, 999999UL);
    Serial.print(F("DS3231 not found - using millis() + offset "));
    Serial.println(bootTimeOffset);
  }

  // Init AT24C256 EEPROM
  readHeader();

  // Init microSD
  if (SD.begin(SD_CS_PIN)) {
    sdAvailable = true;
    Serial.println(F("microSD ready"));
  } else {
    sdAvailable = false;
    Serial.println(F("microSD not found - no SD backup"));
  }

  Serial.println(F("All sensors + storage ready"));
  Serial.print(F("Compiled: "));
  Serial.print(F(__DATE__));
  Serial.print(' ');
  Serial.println(F(__TIME__));
  Serial.println(F("Ozone warming up (~3 min)..."));
  printStatus();
  Serial.println(F("Recording auto-started. Type 'help' for cmds"));
}

void loop() {
  // Handle serial commands (char-by-char, no String class)
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdIdx > 0) {
        cmdBuf[cmdIdx] = '\0';
        processCommand(cmdBuf);
        cmdIdx = 0;
      }
    } else if (cmdIdx < CMD_BUF_SIZE - 1) {
      cmdBuf[cmdIdx++] = c;
    }
  }

  // Read all sensors
  DateTime now = rtcAvailable ? rtc.now() : DateTime((uint32_t)(millis() / 1000) + bootTimeOffset);
  float rtcTemp = rtcAvailable ? rtc.getTemperature() : 0;

  // Read UV
  uint32_t uvs = 0;
  float uvi = NAN;
  bool uvsOk = false;
  if (ltr390Available) {
    ltr390.setMode(LTR390_MODE_UVS);
    delay(300);
    if (ltr390.newDataAvailable()) {
      uvs = ltr390.readUVS();
      uvi = ltr390.getUVI();
      uvsOk = true;
    }
  }

  // Read ambient light
  uint32_t als = 0;
  float lux = NAN;
  bool alsOk = false;
  if (ltr390Available) {
    ltr390.setMode(LTR390_MODE_ALS);
    delay(300);
    if (ltr390.newDataAvailable()) {
      als = ltr390.readALS();
      lux = ltr390.getLux();
      alsOk = true;
    }
  }

  // Reinit LTR390 if either mode failed consecutively
  if (!uvsOk || !alsOk) {
    ltr390Fails++;
    if (ltr390Fails >= SENSOR_REINIT_AFTER) {
      Serial.println(F("LTR390 reinit..."));
      if (ltr390.init()) {
        ltr390.setGain(LTR390_GAIN_3);
        ltr390.setResolution(LTR390_RESOLUTION_18BIT);
        ltr390.enable(true);
        ltr390Available = true;
        Serial.println(F("LTR390 recovered"));
      }
      ltr390Fails = 0;
    }
  } else {
    ltr390Fails = 0;
  }

  // Read pressure + temperature
  float temperature = NAN;
  float pressure = NAN;
  bool ms5607Ok = false;
  if (ms5607Available) {
    ms5607Ok = (ms5607.read() == MS5611_READ_OK);
  }
  if (ms5607Ok) {
    temperature = ms5607.getTemperature();
    pressure = ms5607.getPressure();
    ms5607Fails = 0;
  } else {
    ms5607Fails++;
    if (ms5607Fails >= SENSOR_REINIT_AFTER) {
      Serial.println(F("MS5607 reinit..."));
      if (ms5607.begin()) {
        ms5607.setOversampling(OSR_ULTRA_HIGH);
        ms5607Available = true;
        Serial.println(F("MS5607 recovered"));
      }
      ms5607Fails = 0;
    } else if (ms5607Available) {
      Serial.println(F("MS5607 read error!"));
    }
  }

  // Read ozone (I2C presence check first — library returns 0 when disconnected)
  int16_t ozonePpb = -1;
  if (ozoneAvailable) {
    Wire.beginTransmission(OZONE_ADDRESS_3);
    if (Wire.endTransmission() == 0) {
      ozonePpb = ozone.readOzoneData(COLLECT_NUMBER);
    }
  }
  if (ozonePpb < 0) {
    ozoneFails++;
    if (ozoneFails >= SENSOR_REINIT_AFTER) {
      Serial.println(F("SEN0321 reinit..."));
      if (ozone.begin(OZONE_ADDRESS_3)) {
        ozone.setModes(MEASURE_MODE_PASSIVE);
        ozoneAvailable = true;
        Serial.println(F("SEN0321 recovered"));
      }
      ozoneFails = 0;
    }
  } else {
    ozoneFails = 0;
  }

  // Print live readings
  printDateTime(Serial, now);
  Serial.println();

  Serial.print(F("ALS: "));
  Serial.print(als);
  Serial.print(F(" Lux: "));
  Serial.print(lux);
  Serial.print(F(" | UVS: "));
  Serial.print(uvs);
  Serial.print(F(" UVI: "));
  Serial.println(uvi);

  Serial.print(F("T: "));
  Serial.print(temperature, 2);
  Serial.print(F("C | P: "));
  Serial.print(pressure, 2);
  Serial.println(F("mbar"));

  Serial.print(F("O3: "));
  Serial.print(ozonePpb);
  Serial.print(F("ppb | RTC: "));
  Serial.print(rtcTemp, 2);
  Serial.println('C');

  // Record to SD and EEPROM on separate intervals
  if (recording) {
    unsigned long now_ms = millis();
    uint32_t unixTime = now.unixtime();

    uint8_t sensorFlags = 0;
    if (uvsOk) sensorFlags |= FLAG_UVS_OK;
    if (alsOk) sensorFlags |= FLAG_ALS_OK;
    if (ms5607Ok) sensorFlags |= FLAG_MS5607_OK;
    if (ozonePpb >= 0) sensorFlags |= FLAG_O3_OK;

    // SD card: every recordInterval (10s)
    if (lastRecordTime == 0 || (now_ms - lastRecordTime) >= (unsigned long)recordInterval * 1000UL) {
      lastRecordTime = now_ms;
      sdWriteRecord(now, als, lux, uvs, uvi, temperature, pressure, ozonePpb, rtcTemp, sensorFlags);
      if (sdAvailable) Serial.println(F("[SD]"));
    }

    // EEPROM: every eepromInterval (30s)
    if (lastEepromTime == 0 || (now_ms - lastEepromTime) >= (unsigned long)eepromInterval * 1000UL) {
      lastEepromTime = now_ms;
      bool eepromOk = writeRecord(unixTime, als, lux, uvs, uvi, temperature, pressure, ozonePpb, rtcTemp, sensorFlags);
      if (eepromOk) {
        Serial.print(F("[EEPROM #"));
        Serial.print(recordCount);
        Serial.println(']');
      } else {
        Serial.println(F("[EEPROM full]"));
      }
    }
  }

  Serial.println(F("---"));

  delay(1000);
}
