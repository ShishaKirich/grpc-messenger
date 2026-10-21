// Клиентская часть: генератор паролей, индикатор надёжности, таймер повторной отправки кода.
// Весь код в отдельном файле, потому что политика CSP запрещает встроенные скрипты.
"use strict";

// ---------- генератор паролей ----------
const LOWER = "abcdefghijkmnopqrstuvwxyz";   // без l, чтобы не путать с 1 и I
const UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ";    // без I и O
const DIGITS = "23456789";                   // без 0 и 1
const SYMBOLS = "!@#$%^&*-_=+?";
const ALL = LOWER + UPPER + DIGITS + SYMBOLS;

// Случайное число 0..max-1 из криптографического генератора браузера.
// Отбрасываем «хвост» диапазона, чтобы не было перекоса (modulo bias).
function randomInt(max) {
  const limit = Math.floor(0x100000000 / max) * max;
  const buf = new Uint32Array(1);
  do { crypto.getRandomValues(buf); } while (buf[0] >= limit);
  return buf[0] % max;
}

function pick(chars) { return chars[randomInt(chars.length)]; }

function generatePassword(length = 20) {
  // По одному символу каждого типа, остальное из общего набора, затем перемешиваем (Фишер — Йетс)
  const chars = [pick(LOWER), pick(UPPER), pick(DIGITS), pick(SYMBOLS)];
  while (chars.length < length) chars.push(pick(ALL));
  for (let i = chars.length - 1; i > 0; i--) {
    const j = randomInt(i + 1);
    [chars[i], chars[j]] = [chars[j], chars[i]];
  }
  return chars.join("");
}

// ---------- примерная оценка надёжности (окончательно проверяет сервер) ----------
function estimate(pw) {
  if (!pw) return { score: 0, text: "Используйте длинную фразу или сгенерируйте пароль." };
  let pool = 0;
  if (/[a-zа-яё]/.test(pw)) pool += 26;
  if (/[A-ZА-ЯЁ]/.test(pw)) pool += 26;
  if (/\d/.test(pw)) pool += 10;
  if (/[^a-zA-Zа-яА-ЯёЁ0-9]/.test(pw)) pool += 20;
  let bits = pw.length * Math.log2(Math.max(pool, 1));
  if (/(.)\1{2,}/.test(pw)) bits -= 15;                                 // ааа, 111
  if (/(0123|1234|2345|3456|4567|5678|6789|qwer|asdf|password|пароль)/i.test(pw)) bits -= 25;
  const min = Number(document.querySelector("[data-pw-input]")?.minLength || 10);
  if (pw.length < min) return { score: 0, text: `Слишком короткий: нужно не меньше ${min} символов.` };
  if (bits < 50) return { score: 1, text: "Слабый пароль." };
  if (bits < 70) return { score: 2, text: "Средний пароль. Сделайте длиннее." };
  if (bits < 90) return { score: 3, text: "Хороший пароль." };
  return { score: 4, text: "Отличный пароль." };
}

document.querySelectorAll("[data-pw-block]").forEach((block) => {
  const input = block.querySelector("[data-pw-input]");
  const confirm = block.querySelector("[data-pw-confirm]");
  const bar = block.querySelector("[data-pw-bar]");
  const hint = block.querySelector("[data-pw-hint]");
  const copyBtn = block.querySelector("[data-pw-copy]");

  const update = () => {
    const { score, text } = estimate(input.value);
    bar.style.width = `${input.value ? (score + 1) * 20 : 0}%`;
    bar.dataset.score = score;
    hint.textContent = text;
    confirm.setCustomValidity(confirm.value && confirm.value !== input.value ? "Пароли не совпадают" : "");
  };
  input.addEventListener("input", update);
  confirm.addEventListener("input", update);

  block.querySelector("[data-pw-toggle]").addEventListener("click", () => {
    const show = input.type === "password";
    input.type = confirm.type = show ? "text" : "password";
  });

  block.querySelector("[data-pw-generate]").addEventListener("click", () => {
    const pw = generatePassword();
    input.value = confirm.value = pw;
    input.type = confirm.type = "text";  // показываем, чтобы пользователь мог его сохранить
    copyBtn.hidden = false;
    update();
  });

  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(input.value);
      copyBtn.textContent = "Скопировано";
      setTimeout(() => { copyBtn.textContent = "Скопировать"; }, 2000);
    } catch { input.select(); }
  });
});

// ---------- таймер «Отправить код ещё раз» ----------
document.querySelectorAll("[data-countdown]").forEach((btn) => {
  let wait = Number(btn.dataset.countdown);
  const label = btn.textContent.trim();
  const tick = () => {
    if (wait > 0) { btn.textContent = `${label} через ${wait} с`; wait--; setTimeout(tick, 1000); }
    else { btn.textContent = label; btn.disabled = false; }
  };
  tick();
});

// ---------- копирование резервных кодов ----------
document.querySelectorAll("[data-copy-backup]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const codes = [...document.querySelectorAll("[data-backup-codes] code")].map((c) => c.textContent).join("\n");
    try {
      await navigator.clipboard.writeText(codes);
      btn.textContent = "Скопировано";
    } catch { /* без доступа к буферу обмена коды можно выделить вручную */ }
  });
});
