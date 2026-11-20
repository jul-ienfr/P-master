#![allow(dead_code)]

// Jeux de test partagés (Kuhn et Leduc), réutilisés par les tests de
// convergence de schedule (`tests/cfr_schedule_convergence.rs`, spec `012`).
// Valeurs de référence vérifiées contre OpenSpiel (voir les tests).
pub mod kuhn;
pub mod leduc;
pub mod schedule_bench;
