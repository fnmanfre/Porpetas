import json
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Personal Chef – Calculadora", page_icon="🥘", layout="wide")

# --------------------------- Data Models ---------------------------

@dataclass
class Ingredient:
    name: str
    unitPurchase: str  # "kg" | "ml" | "un"
    rl: float          # rendimento líquido (0-1)
    price: Optional[float] = None  # preço por unidade de compra
    # Campos de nutrição e densidade
    kcal_per_100g: Optional[float] = None      # para itens em g/ml (usando densidade)
    kcal_per_unit: Optional[float] = None      # para itens por unidade (ex.: ovo)
    density_g_per_ml: Optional[float] = None   # se item está em ml, para converter ml -> g (padrão 1.0 se None)

@dataclass
class RecipeItem:
    ingredient: str    # reference to Ingredient.name
    perPersonPL: float # quantidade por pessoa (líquido)
    unit: str          # "g" | "ml" | "un"
    fc: float = 1.0    # fator de cocção
    note: str = ""

@dataclass
class Recipe:
    name: str
    items: List[RecipeItem]

# --------------------------- Starter Data ---------------------------

SAMPLE_INGREDIENTS = [
    Ingredient("Cebola", "kg", 0.88, 6.90, kcal_per_100g=40),
    Ingredient("Alho", "kg", 0.92, 24.00, kcal_per_100g=149),
    Ingredient("Tomate", "kg", 0.90, 8.50, kcal_per_100g=18),
    Ingredient("Cenoura", "kg", 0.85, 7.90, kcal_per_100g=41),
    Ingredient("Batata inglesa", "kg", 0.85, 5.90, kcal_per_100g=77),
    Ingredient("Alface americana", "un", 0.80, 6.50, kcal_per_100g=15),
    Ingredient("Peito de frango", "kg", 0.90, 22.90, kcal_per_100g=165),
    Ingredient("Coxão mole (limpo)", "kg", 0.80, 34.90, kcal_per_100g=217),
    Ingredient("Arroz branco (cru)", "kg", 1.00, 6.20, kcal_per_100g=365),
    Ingredient("Feijão carioca (cru)", "kg", 1.00, 9.50, kcal_per_100g=333),
    Ingredient("Azeite", "ml", 1.00, 34.90, kcal_per_100g=884, density_g_per_ml=0.91),
    Ingredient("Ovo", "un", 1.00, 0.90, kcal_per_unit=68),
    Ingredient("Leite", "ml", 1.00, 5.50, kcal_per_100g=61, density_g_per_ml=1.03),
    Ingredient("Farinha de trigo", "kg", 1.00, 5.20, kcal_per_100g=364),
    Ingredient("Mussarela", "kg", 0.98, 38.00, kcal_per_100g=280),
    Ingredient("Tilápia (filé)", "kg", 0.95, 42.00, kcal_per_100g=96),
]

SAMPLE_RECIPES = [
    Recipe(
        "Frango grelhado + arroz + salada",
        [
            RecipeItem("Peito de frango", 150, "g", 0.88),
            RecipeItem("Arroz branco (cru)", 70, "g", 2.7, "Fator de cozimento → peso servido"),
            RecipeItem("Alface americana", 100, "g", 1.0),
            RecipeItem("Tomate", 60, "g", 1.0),
            RecipeItem("Cebola", 20, "g", 0.9),
            RecipeItem("Azeite", 10, "ml", 1.0),
        ],
    ),
    Recipe(
        "Tilápia assada + batata + salada",
        [
            RecipeItem("Tilápia (filé)", 160, "g", 0.92),
            RecipeItem("Batata inglesa", 200, "g", 0.85),
            RecipeItem("Alface americana", 80, "g", 1.0),
            RecipeItem("Tomate", 60, "g", 1.0),
            RecipeItem("Cebola", 15, "g", 0.9),
            RecipeItem("Azeite", 10, "ml", 1.0),
        ],
    ),
]

# --------------------------- Session State ---------------------------

def init_state():
    if "ingredients" not in st.session_state:
        st.session_state.ingredients = SAMPLE_INGREDIENTS.copy()
    if "recipes" not in st.session_state:
        st.session_state.recipes = SAMPLE_RECIPES.copy()
    if "selected_recipe" not in st.session_state:
        st.session_state.selected_recipe = st.session_state.recipes[0].name if st.session_state.recipes else ""
    if "people" not in st.session_state:
        st.session_state.people = 4
    if "target_served_per_person_g" not in st.session_state:
        st.session_state.target_served_per_person_g = None

init_state()

def ingredient_map() -> Dict[str, Ingredient]:
    return {ing.name: ing for ing in st.session_state.ingredients}

# --------------------------- Nutrition helpers ---------------------------

def kcal_for_item(ing: Ingredient, cooked_weight_g: float, unit: str) -> Optional[float]:
    """
    Retorna kcal do item considerando o peso/quantidade servido.
    - Para g/ml: usa kcal_per_100g * gramas. Para ml, converte ml->g via densidade (padrão 1.0 se None).
    - Para 'un': usa kcal_per_unit * unidades (aqui, cooked_weight_g representa 'unidades' se unit=='un').
    """
    if unit == "un":
        if ing.kcal_per_unit is None:
            return None
        return ing.kcal_per_unit * cooked_weight_g

    if ing.kcal_per_100g is None:
        return None

    grams = cooked_weight_g
    if unit == "ml":
        dens = ing.density_g_per_ml if ing.density_g_per_ml is not None else 1.0
        grams = cooked_weight_g * dens
    return ing.kcal_per_100g * grams / 100.0

# --------------------------- Calculations ---------------------------

def compute_rows(recipe: Recipe, people: int, target_served_per_person_g: Optional[float]) -> Tuple[pd.DataFrame, Dict[str, float]]:
    ing_idx = ingredient_map()

    # agrega por ingrediente+unidade de receita
    agg: Dict[str, Dict] = {}
    for it in recipe.items:
        key = f"{it.ingredient}__{it.unit}"
        ing = ing_idx.get(it.ingredient, None)
        if key not in agg:
            agg[key] = {
                "Ingrediente": it.ingredient,
                "UnitCompra": ing.unitPurchase if ing else "kg",
                "PL_pessoa": float(it.perPersonPL),
                "Un": it.unit,
                "Pessoas": int(people),
                "RL": float(ing.rl if ing else 1.0),
                "FC": float(it.fc if it.fc else 1.0),
                "Obs": it.note or "",
            }
        else:
            agg[key]["PL_pessoa"] += float(it.perPersonPL)
            agg[key]["FC"] = float(it.fc if it.fc else 1.0)

    # peso servido atual (apenas g/ml) para calcular escala, se alvo informado
    served_total_per_person_g = 0.0
    for r in agg.values():
        if r["Un"] != "un":
            served_total_per_person_g += r["PL_pessoa"] * r["FC"]

    scale = 1.0
    if target_served_per_person_g and target_served_per_person_g > 0 and served_total_per_person_g > 0:
        scale = target_served_per_person_g / served_total_per_person_g

    rows = []
    kcal_person = 0.0
    total_served_weight_per_person = 0.0

    for r in agg.items():
        k, r = r
        pl_pessoa_scaled = r["PL_pessoa"] * scale
        pl_total = pl_pessoa_scaled * r["Pessoas"]
        rl = r["RL"] if r["RL"] > 0 else 1.0
        pb_total = pl_total / rl  # quantidade bruta necessária (antes de perdas)

        # conversão para unidade de compra
        purchase_qty = pb_total
        if r["UnitCompra"] == "kg" and r["Un"] == "g":
            purchase_qty = pb_total / 1000.0
        elif r["UnitCompra"] == "ml" and r["Un"] == "ml":
            purchase_qty = pb_total
        elif r["UnitCompra"] == "un" and r["Un"] == "un":
            purchase_qty = pb_total
        # OBS: quando UnitCompra='un' e a receita está em 'g/ml', não há peso por unidade cadastrado.
        # Mantemos 'purchase_qty' como pb_total (fallback). Ajuste manual pode ser necessário.

        ing = ing_idx.get(r["Ingrediente"])
        price = ing.price if ing else None
        cost = (purchase_qty * price) if (price is not None) else None

        # Quantidade servida (após FC)
        if r["Un"] in ("g", "ml"):
            per_person_cooked = pl_pessoa_scaled * r["FC"]
            total_cooked = pl_total * r["FC"]
        else:
            # 'un' — trata como unidades (FC aplicado apenas se você usa FC para perdas em unidades)
            per_person_cooked = pl_pessoa_scaled * r["FC"]
            total_cooked = pl_total * r["FC"]

        # Nutrição
        kcal_this = None
        if ing is not None:
            if r["Un"] in ("g", "ml"):
                kcal_this = kcal_for_item(ing, per_person_cooked, r["Un"])
            elif r["Un"] == "un":
                kcal_this = kcal_for_item(ing, per_person_cooked, "un")

        if kcal_this is not None:
            kcal_person += kcal_this
        if r["Un"] != "un":
            total_served_weight_per_person += per_person_cooked

        rows.append({
            "Ingrediente": r["Ingrediente"],
            "Un. compra": r["UnitCompra"],
            "PL/pessoa": pl_pessoa_scaled,
            "Un (g/ml/un)": r["Un"],
            "Pessoas": r["Pessoas"],
            "PL total": pl_total,
            "RL": rl,
            "PB total": pb_total,
            "Qtd p/ compra": purchase_qty,
            "Preço (un. compra)": price,
            "Custo": cost,
            "FC": r["FC"],
            "Peso final/pessoa": per_person_cooked,
            "Peso final total": total_cooked,
            "kcal/pessoa (ingrediente)": kcal_this,
            "Obs": r["Obs"],
        })

    df = pd.DataFrame(rows)
    cols = [
        "Ingrediente","Un. compra","PL/pessoa","Un (g/ml/un)","Pessoas","PL total","RL","PB total",
        "Qtd p/ compra","Preço (un. compra)","Custo","FC","Peso final/pessoa","Peso final total",
        "kcal/pessoa (ingrediente)","Obs"
    ]
    if not df.empty:
        df = df[cols]

    summary = {
        "kcal_por_pessoa": float(kcal_person) if kcal_person else 0.0,
        "peso_servido_por_pessoa_g": float(total_served_weight_per_person) if total_served_weight_per_person else 0.0,
    }
    if summary["peso_servido_por_pessoa_g"] > 0:
        summary["kcal_por_grama"] = summary["kcal_por_pessoa"] / summary["peso_servido_por_pessoa_g"]
        summary["kcal_por_200g"] = summary["kcal_por_grama"] * 200.0
        summary["kcal_totais_receita"] = summary["kcal_por_pessoa"] * (int(df["Pessoas"].iloc[0]) if not df.empty else people)
    else:
        summary["kcal_por_grama"] = 0.0
        summary["kcal_por_200g"] = 0.0
        summary["kcal_totais_receita"] = 0.0

    return df, summary

# --------------------------- Sidebar ---------------------------

with st.sidebar:
    st.header("Configuração")
    # Select recipe
    recipe_names = [r.name for r in st.session_state.recipes]
    if recipe_names:
        idx = recipe_names.index(st.session_state.selected_recipe) if st.session_state.selected_recipe in recipe_names else 0
        st.session_state.selected_recipe = st.selectbox("Receita", recipe_names, index=idx)
    st.session_state.people = int(st.number_input("Número de pessoas", min_value=1, value=st.session_state.people, step=1))

    # Alvo de porção servida por pessoa (g) – opcional
    target = st.text_input("Alvo de porção servida por pessoa (g) – opcional", value=str(st.session_state.target_served_per_person_g or ""))
    try:
        tval = float(target.replace(",", ".")) if target.strip() else None
    except Exception:
        tval = None
    st.session_state.target_served_per_person_g = tval

    st.markdown("---")
    st.subheader("Exportar/Importar")
    col_a, col_b = st.columns(2)
    with col_a:
        st.download_button(
            "Exportar JSON (dados)",
            data=json.dumps({
                "ingredients": [asdict(i) for i in st.session_state.ingredients],
                "recipes": [
                    {"name": r.name, "items": [asdict(it) for it in r.items]}
                    for r in st.session_state.recipes
                ],
            }, indent=2, ensure_ascii=False).encode("utf-8"),
            file_name="personal-chef-dados.json",
            mime="application/json; charset=utf-8",
        )
    with col_b:
        pass

    up = st.file_uploader("Importar JSON (dados)", type=["json"])
    if up is not None:
        try:
            data = json.loads(up.read().decode("utf-8"))
            if "ingredients" in data and isinstance(data["ingredients"], list):
                st.session_state.ingredients = [Ingredient(**i) for i in data["ingredients"]]
            if "recipes" in data and isinstance(data["recipes"], list):
                new_recipes: List[Recipe] = []
                for r in data["recipes"]:
                    items = [RecipeItem(**it) for it in r.get("items", [])]
                    new_recipes.append(Recipe(name=r["name"], items=items))
                st.session_state.recipes = new_recipes
                if new_recipes:
                    st.session_state.selected_recipe = new_recipes[0].name
            st.success("Dados importados!")
        except Exception as e:
            st.error(f"Falha ao importar JSON: {e}")

# --------------------------- Main: Ingredients ---------------------------

st.title("🥘 Personal Chef – Calculadora de Compras (Python) + Calorias")
st.caption("PL = peso líquido por pessoa. RL = rendimento líquido. PB = PL/RL (compra). FC = fator de cocção. Calorias baseadas em kcal/100g, kcal/un e densidade opcional.")

st.subheader("Cadastro de ingredientes")
ing_df = pd.DataFrame([asdict(i) for i in st.session_state.ingredients])
ing_edited = st.data_editor(
    ing_df,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "name": st.column_config.TextColumn("Nome"),
        "unitPurchase": st.column_config.SelectboxColumn("Unidade de compra", options=["kg", "ml", "un"]),
        "rl": st.column_config.NumberColumn("RL (0-1)", min_value=0.0, max_value=1.0, step=0.01, format="%.2f"),
        "price": st.column_config.NumberColumn("Preço por unidade de compra", step=0.01, format="%.2f"),
        "kcal_per_100g": st.column_config.NumberColumn("kcal/100g (g/ml)", step=1.0, format="%.0f"),
        "kcal_per_unit": st.column_config.NumberColumn("kcal/un (se unitário)", step=1.0, format="%.0f"),
        "density_g_per_ml": st.column_config.NumberColumn("Densidade g/ml (opcional)", step=0.01, format="%.2f"),
    },
    hide_index=True,
)
try:
    st.session_state.ingredients = [Ingredient(**row) for row in ing_edited.to_dict(orient="records")]
except Exception as e:
    st.warning(f"Verifique o cadastro de ingredientes: {e}")

# --------------------------- Recipes Editor ---------------------------

st.subheader("Receita")
recipes_map = {r.name: r for r in st.session_state.recipes}
if st.session_state.selected_recipe not in recipes_map and st.session_state.recipes:
    st.session_state.selected_recipe = st.session_state.recipes[0].name

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    new_name = st.text_input("Nome da receita selecionada", value=st.session_state.selected_recipe)
with col2:
    if st.button("Salvar nome"):
        if new_name.strip():
            r = recipes_map.pop(st.session_state.selected_recipe, None)
            if r:
                r.name = new_name.strip()
                recipes_map[r.name] = r
                st.session_state.recipes = list(recipes_map.values())
                st.session_state.selected_recipe = r.name
with col3:
    if st.button("Nova receita"):
        r = Recipe(name=f"Nova receita {len(st.session_state.recipes)+1}", items=[])
        st.session_state.recipes.append(r)
        st.session_state.selected_recipe = r.name

current_recipe = recipes_map.get(st.session_state.selected_recipe) if st.session_state.recipes else None

if current_recipe is None:
    st.info("Crie ou selecione uma receita.")
else:
    items_df = pd.DataFrame([asdict(it) for it in current_recipe.items])
    ingredient_names = [i.name for i in st.session_state.ingredients]
    if items_df.empty:
        items_df = pd.DataFrame(columns=["ingredient", "perPersonPL", "unit", "fc", "note"])

    items_edited = st.data_editor(
        items_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "ingredient": st.column_config.SelectboxColumn("Ingrediente", options=ingredient_names),
            "perPersonPL": st.column_config.NumberColumn("PL por pessoa", step=1.0, format="%.2f"),
            "unit": st.column_config.SelectboxColumn("Un (g/ml/un)", options=["g", "ml", "un"]),
            "fc": st.column_config.NumberColumn("FC", step=0.01, format="%.2f"),
            "note": st.column_config.TextColumn("Observações"),
        },
        hide_index=True,
    )

    try:
        current_recipe.items = [RecipeItem(**row) for row in items_edited.to_dict(orient="records")]
        for i, r in enumerate(st.session_state.recipes):
            if r.name == current_recipe.name:
                st.session_state.recipes[i] = current_recipe
    except Exception as e:
        st.warning(f"Verifique os itens da receita: {e}")

# --------------------------- Calculated Shopping List + Nutrition ---------------------------

st.subheader("Lista de compras e calorias")
if st.session_state.recipes and current_recipe is not None:
    df, summary = compute_rows(current_recipe, st.session_state.people, st.session_state.target_served_per_person_g)
    st.dataframe(df, use_container_width=True)

    # Totais
    if not df.empty:
        total_cost = df["Custo"].dropna().sum()
        st.markdown(f"**Custo total estimado:** R$ {total_cost:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

    # Nutrição resumo
    st.markdown("### Resumo nutricional")
    colA, colB, colC, colD = st.columns(4)
    with colA:
        st.metric("kcal por pessoa", f"{summary['kcal_por_pessoa']:.0f} kcal")
    with colB:
        st.metric("Peso servido por pessoa", f"{summary['peso_servido_por_pessoa_g']:.0f} g")
    with colC:
        st.metric("kcal por 200 g", f"{summary['kcal_por_200g']:.0f} kcal")
    with colD:
        st.metric("kcal totais da receita", f"{summary['kcal_totais_receita']:.0f} kcal")

    # Export buttons
    colx, coly = st.columns(2)
    with colx:
        st.download_button("Exportar CSV (lista)", data=df.to_csv(index=False).encode("utf-8"), file_name="lista-de-compras.csv", mime="text/csv; charset=utf-8")
    with coly:
        st.download_button(
            "Exportar JSON (lista)",
            data=json.dumps({"rows": df.to_dict(orient="records"), "summary": summary}, indent=2, ensure_ascii=False).encode("utf-8"),
            file_name="lista-de-compras.json",
            mime="application/json; charset=utf-8"
        )
else:
    st.info("Cadastre ingredientes e itens da receita para ver a lista de compras.")

st.markdown("---")
st.caption("Notas: kcal aproximadas; cozidos complexos (ensopados) podem mudar densidade. Para ml, ajuste densidade g/ml (ex.: azeite ~0,91). Use o alvo de porção servida para escalar a receita a 200 g por pessoa, por exemplo.")
