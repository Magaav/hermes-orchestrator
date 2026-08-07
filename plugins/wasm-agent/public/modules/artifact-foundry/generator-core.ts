const INPUT_CAPACITY: i32 = 1 << 20;
const OUTPUT_CAPACITY: i32 = 1 << 24;
const input = new StaticArray<u8>(INPUT_CAPACITY);
const output = new StaticArray<u8>(OUTPUT_CAPACITY);

export function inputPtr(): usize {
  return changetype<usize>(input);
}

export function outputPtr(): usize {
  return changetype<usize>(output);
}

export function inputCapacity(): i32 {
  return INPUT_CAPACITY;
}

export function shellOf(ties: i32): i32 {
  let shell = 0;
  let rung = 1;
  while (rung < ties && shell < 12) {
    rung *= 3;
    shell += 1;
  }
  return shell;
}

export function pump(inputLength: i32, rounds: i32): i32 {
  if (inputLength < 0 || inputLength > INPUT_CAPACITY || rounds < 0 || rounds > 4) return -1;
  let currentLength = inputLength;
  for (let index = 0; index < currentLength; index += 1) {
    unchecked(output[index] = input[index]);
  }
  for (let round = 0; round < rounds; round += 1) {
    const aligned = (currentLength / 3) * 3;
    if (aligned * 3 > OUTPUT_CAPACITY) return -2;
    for (let index = aligned - 1; index >= 0; index -= 1) {
      const value = unchecked(output[index]);
      const next = unchecked(output[(index + 3) % aligned]);
      unchecked(output[index + aligned * 2] = <u8>((value * 3 + 1) & 255));
      unchecked(output[index + aligned] = <u8>((value + next) & 255));
    }
    currentLength = aligned * 3;
  }
  return currentLength;
}
