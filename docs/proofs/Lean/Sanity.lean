-- Sanity check that the Lean 4 toolchain works on a trivial theorem.

theorem one_plus_one : 1 + 1 = 2 := rfl

theorem add_comm_nat (a b : Nat) : a + b = b + a := by
  exact Nat.add_comm a b

#check @one_plus_one
#check @add_comm_nat
