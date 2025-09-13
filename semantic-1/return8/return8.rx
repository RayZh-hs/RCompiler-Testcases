/*
Test Package: Semantic-1
Test Target: return
Author: Ruitian Wang
Time: 2025-08-27
Verdict: Pass
Comment: Valid return with complex expression
*/

// Valid: return with complex expression
fn calculate(a: i32, b: i32) -> i32 {
    if (a > b) {
        return a * b + (a - b);
    } else if (a == b) {
        return a * 2;
    }
    return (b - a);
}

fn main() {
    let result1: i32 = calculate(10, 5);
    let result2: i32 = calculate(3, 3);
    let result3: i32 = calculate(2, 8);
    exit(0);
}
