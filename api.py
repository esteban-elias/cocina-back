import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

app = FastAPI(title="Cocina API", version="1.0.0")


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database configuration
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_NAME", "cocina"),
    "user": os.getenv("DB_USER", "s7"),
    "password": os.getenv("DB_PASSWORD", "123456"),
}


def get_db_connection():
    """Create and return a database connection."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")


@app.get("/")
def read_root():
    return {"message": "Cocina API - Use /docs for API documentation"}


@app.get("/recipes/{user_id}")
def get_recipes(user_id: int):
    """
    Get all the cookable recipes (0 missing ingredient) and almost cookable recipes
    (1 missing ingredient) for a user

    """
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # First, verify the user exists
            cursor.execute('SELECT id, name FROM "user" WHERE id = %s', (user_id,))
            user = cursor.fetchone()
            if not user:
                raise HTTPException(status_code=404, detail=f"User with id {user_id} not found")

            # Get all ingredients on database
            query = """
SELECT * FROM ingredient;
"""
            cursor.execute(query)
            all_ingredients = cursor.fetchall()

            # Get all ingredients of user
            query = """
SELECT * FROM "user"
INNER JOIN user_ingredient ON "user".id = user_ingredient.user_id
INNER JOIN ingredient ON user_ingredient.ingredient_id = ingredient.id
WHERE "user".id = %s;
"""
            cursor.execute(query, (user_id,))
            user_ingredients = cursor.fetchall()
            
            # Get all the recipes on the database
            query = """
SELECT * FROM recipe;
"""
            cursor.execute(query)
            all_recipes = cursor.fetchall()

            # Get all the recipe_ingredient junctions and filter by user
            query = """
SELECT * FROM recipe_ingredient;
"""
            cursor.execute(query)
            recipe_ingredient_junctions = cursor.fetchall()

            # Filter recipe_ingredient_junctions of user ingredients
            user_ingredients_ids = [ingredient['id'] for ingredient in user_ingredients]
            user_recipe_ingredient_junctions = []
            for junction in recipe_ingredient_junctions:
                if junction['ingredient_id'] in user_ingredients_ids:
                    user_recipe_ingredient_junctions.append(junction)

            # Get all user recipes (at least 1 matching ingredient)
            user_recipes_ids = [junction['recipe_id'] for junction in user_recipe_ingredient_junctions]
            user_recipes = []
            for recipe in all_recipes:
                if recipe['id'] in user_recipes_ids:
                    user_recipes.append(recipe)

            # Extend user_recipes with its ingredients 
            for recipe in user_recipes:
                ingredients_ids = [
                    junction['ingredient_id'] for junction in recipe_ingredient_junctions if recipe['id'] == junction['recipe_id']
                ]
                ingredients = [
                    ingredient for ingredient in all_ingredients if ingredient['id'] in ingredients_ids
                ]
                recipe['ingredients'] = ingredients

            # Extend user_recipes with its missing ingredients
            for recipe in user_recipes:
                missing_ingredients = [
                    ingredient for ingredient in recipe['ingredients'] if ingredient['id'] not in user_ingredients_ids
                ]
                recipe['missing_ingredients'] = missing_ingredients

            # Get cookable recipes (0 missing ingredients)
            cookable_recipes = [
                recipe for recipe in user_recipes if len(recipe['missing_ingredients']) == 0
            ]
            
            # Get almost cookable recipes (1 missing ingredients)
            almost_cookable_recipes = [
                recipe for recipe in user_recipes if len(recipe['missing_ingredients']) == 1
            ]


            # Extend 'missing_ingredients' of almost_cookable_recipes with related products
            query = """
SELECT * FROM product;
"""
            cursor.execute(query)
            products = cursor.fetchall()

            for recipe in almost_cookable_recipes:
                recipe['missing_ingredients'][0]['products'] = [
                    product for product in products if product['ingredient_id'] == recipe['missing_ingredients'][0]['id']
                ]

            return {
                'cookable_recipes': cookable_recipes,
                'almost_cookable_recipes': almost_cookable_recipes,
            }

    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        conn.close()


