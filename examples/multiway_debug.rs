use postflop_solver::{solve_multiway, MultiwayRequest};

fn parse_args() -> (usize, Vec<String>, u32, Option<u64>) {
    let args: Vec<String> = std::env::args().collect();
    let mut n: usize = 3;
    let mut board: Vec<String> = vec!["Jh".to_string(), "7d".to_string(), "2c".to_string()];
    let mut iters: u32 = 100_000;
    let mut seed: Option<u64> = Some(42);
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--n" if i + 1 < args.len() => {
                n = args[i + 1].parse().unwrap_or(3);
                i += 2;
            }
            "--board" if i + 1 < args.len() => {
                let raw = args[i + 1].trim().to_string();
                if raw.is_empty() || raw == "\"\"" || raw == "''" {
                    board = vec![];
                } else {
                    board = raw
                        .split(|c| c == ',' || c == ' ')
                        .filter(|s| !s.is_empty())
                        .map(|s| s.to_string())
                        .collect();
                    // single concatenated form like "Ah7d2c" -> ["Ah","7d","2c"]
                    if board.len() == 1 && board[0].len() > 2 && board[0].len() % 2 == 0 {
                        let s = board[0].clone();
                        board = s
                            .as_bytes()
                            .chunks(2)
                            .map(|c| String::from_utf8_lossy(c).to_string())
                            .collect();
                    }
                }
                i += 2;
            }
            "--iters" if i + 1 < args.len() => {
                iters = args[i + 1].parse().unwrap_or(100_000);
                i += 2;
            }
            "--seed" if i + 1 < args.len() => {
                seed = Some(args[i + 1].parse().unwrap_or(42));
                i += 2;
            }
            _ => i += 1,
        }
    }
    (n, board, iters, seed)
}

fn main() {
    let (n, board, max_iterations, random_seed) = parse_args();
    // Board-aware pool : Ah/Kx massivement bloqués → starvation 6-way
    // sur Ah7d2c (≈48% sur 2500). On détecte et on bascule sur pool
    // disjoint (paires basses / suited broadways non-As) garanti >80%.
    // Cas nominal : pool identique tests (AA/KK/QQ/JJ/TT/AKs).
    let board_has_ace = board.iter().any(|c| c.starts_with('A'));
    let board_has_king = board.iter().any(|c| c.starts_with('K'));
    let use_avoid_pool = n >= 5 && (board_has_ace || board_has_king);
    let ranges: Vec<String> = if use_avoid_pool {
        // 6 ranks qui n'utilisent ni A ni K → aucune collision avec Ah/Kx
        let pool_avoid = ["QQ", "JJ", "TT", "99", "88", "77"];
        (0..n).map(|i| pool_avoid[i % pool_avoid.len()].to_string()).collect()
    } else {
        let pool = ["AA", "KK", "QQ", "JJ", "TT", "AKs"];
        let mut r: Vec<String> = (0..n).map(|i| pool[i % pool.len()].to_string()).collect();
        // Mode démo pédagogique : si n==3 et board par défaut Jh7d2c, on garde
        // 92o en hero pour illustrer le contraste weak vs strong (seulement invocation sans args).
        let is_default_board = board == vec!["Jh".to_string(), "7d".to_string(), "2c".to_string()];
        if n == 3 && is_default_board && std::env::args().len() == 1 {
            r[0] = "92o".to_string();
        }
        r
    };
    let request = MultiwayRequest {
        ranges,
        board,
        starting_pot: 6.0,
        effective_stack: 20.0,
        hero_player: 0,
        max_iterations,
        random_seed,
        rake_rate: 0.0,
        rake_cap: 0.0,
    };
    let response = solve_multiway(request).expect("solve");
    println!("action: {}", response.recommended_action);
    println!("ev: {:.4}", response.hero_ev);
    println!(
        "actions: {:?}",
        response
            .actions
            .iter()
            .map(|a| (a.name.clone(), a.frequency))
            .collect::<Vec<_>>()
    );
}
