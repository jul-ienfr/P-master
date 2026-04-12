use postflop_solver::{solve_spot, SolveRequest};

fn build_request(board: &[&str]) -> SolveRequest {
    SolveRequest {
        oop_range: "AsKs".to_string(),
        ip_range: "QQ+".to_string(),
        board: board.iter().map(|card| card.to_string()).collect(),
        starting_pot: 4.0,
        effective_stack: 100.0,
        hero_is_oop: true,
        max_iterations: 10,
        target_exploitability: 1.0,
        use_cache: true,
    }
}

fn percentile_95(values: &[u64]) -> u64 {
    if values.is_empty() {
        return 0;
    }
    let mut ordered = values.to_vec();
    ordered.sort_unstable();
    let index = ((ordered.len() - 1) as f32 * 0.95).round() as usize;
    ordered[index.min(ordered.len() - 1)]
}

fn main() {
    let warm_request = build_request(&["Ah", "7d", "2c", "9h", "Td"]);
    let prime = solve_spot(warm_request.clone()).expect("prime warm request");

    let mut warm_ms = Vec::new();
    let mut warm_cache_hits = 0u32;
    for _ in 0..5 {
        let response = solve_spot(warm_request.clone()).expect("warm request");
        if response.cache_hit {
            warm_cache_hits += 1;
        }
        warm_ms.push(response.elapsed_ms);
    }

    let cold_boards = [
        ["Kd", "8s", "3c", "2d", "Jh"],
        ["Qc", "7h", "2d", "4s", "9c"],
        ["Js", "9d", "4c", "2h", "Ad"],
        ["Th", "6c", "2s", "8d", "Kh"],
        ["9c", "7d", "5h", "2c", "Qd"],
    ];
    let mut cold_ms = Vec::new();
    let mut cold_cache_hits = 0u32;
    for board in cold_boards {
        let response = solve_spot(build_request(&board)).expect("cold request");
        if response.cache_hit {
            cold_cache_hits += 1;
        }
        cold_ms.push(response.elapsed_ms);
    }

    println!(
        "{{\"kind\":\"native_latency\",\"warm\":{{\"samples_ms\":{:?},\"p95_ms\":{},\"cache_hits\":{},\"prime_elapsed_ms\":{}}},\"cold\":{{\"samples_ms\":{:?},\"p95_ms\":{},\"cache_hits\":{}}}}}",
        warm_ms,
        percentile_95(&warm_ms),
        warm_cache_hits,
        prime.elapsed_ms,
        cold_ms,
        percentile_95(&cold_ms),
        cold_cache_hits
    );
}
