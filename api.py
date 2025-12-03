import base64
from dotenv import load_dotenv
import json
import os
from fastapi import FastAPI, File, HTTPException, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage


load_dotenv()


class ImageScanRequest(BaseModel):
    image_url: str


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
    Get all the recipes whose ingredients match at least 1 user's ingredient.
    Include matching ingredients and missing ingredients.
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
                matching_ingredients = []
                missing_ingredients = []
                for ingredient in recipe['ingredients']:
                    if ingredient['id'] in user_ingredients_ids:
                        matching_ingredients.append(ingredient)
                    else:
                        missing_ingredients.append(ingredient)
                recipe['matching_ingredients'] = matching_ingredients
                recipe['missing_ingredients'] = missing_ingredients

            return {
                'recipes': user_recipes,
            }

    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        conn.close()


@app.get("/ingredients/{user_id}")
def get_user_ingredients(user_id: int):
    """
    Get all ingredients of a user.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Verify the user exists
            cursor.execute('SELECT id FROM "user" WHERE id = %s', (user_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail=f"User with id {user_id} not found")

            # Join the ingredient table with the junction table
            query = """
            SELECT i.id, i.name 
            FROM ingredient i
            JOIN user_ingredient ui ON i.id = ui.ingredient_id
            WHERE ui.user_id = %s
            ORDER BY i.name ASC;
            """
            
            cursor.execute(query, (user_id,))
            user_ingredients = cursor.fetchall()

            return user_ingredients

    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        conn.close()


@app.post("/scan-ingredients")
async def scan_ingredients(file: UploadFile = File(...)):
    """
    Receives an image file upload, fetches all known ingredients from the DB,
    and asks Gemini to identify which of those ingredients appear in the image.
    """
    conn = get_db_connection()
    try:
        # Fetch the master list of ingredients from the database
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT id, name FROM ingredient")
            db_ingredients = cursor.fetchall()

        # Convert to a simplified string/JSON representation for the prompt
        ingredients_context = ", ".join([f"{ing['id']}: {ing['name']}" for ing in db_ingredients])

        # Setup LLM
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0,
            max_retries=2,
        )

        # Read and encode the uploaded file
        image_data = await file.read()
        if not image_data:
            raise HTTPException(status_code=400, detail="Empty or invalid image file")

        # Detect MIME type (e.g., 'jpeg', 'png') from UploadFile
        content_type = file.content_type.split('/')[-1] if file.content_type else 'jpeg'  # Fallback to jpeg if unknown

        # Base64 encode for inline data URI
        base64_image = base64.b64encode(image_data).decode('utf-8')

        # Construct the Multimodal Prompt
        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": f"""
                    You are a cooking assistant API. 
                    I will provide a list of valid ingredients from my database (ID: NAME).
                    
                    Your task:
                    1. Analyze the provided image.
                    2. Identify food ingredients visible in the image.
                    3. Match them STRICTLY to the provided database list.
                    4. Ignore any items in the image that do not match a name in the list.
                    5. Return ONLY a valid JSON list of objects.

                    Database List:
                    [{ingredients_context}]

                    Output Format required:
                    [
                        {{"id": 123, "name": "tomato"}},
                        {{"id": 456, "name": "onion"}}
                    ]
                    
                    Return ONLY the JSON. No markdown, no explanations.
                    """
                },
                {
                    "type": "image_url",
                    "image_url": f"data:image/{content_type};base64,{base64_image}"  # NEW: Use base64 data URI
                }
            ]
        )

        # Invoke LLM
        response = llm.invoke([message])
        
        # Clean and Parse JSON
        content = response.content.strip()
        
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "")
        elif content.startswith("```"):
            content = content.replace("```", "")

        detected_ingredients = json.loads(content)

        return {
            "status": "success",
            "detected_count": len(detected_ingredients),
            "ingredients": detected_ingredients
        }

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse AI response. The model did not return valid JSON.")
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")
    finally:
        conn.close()


@app.post("/ingredients/{user_id}")
def add_user_ingredients(user_id: int, ingredient_ids: List[int]):
    """
    Add ingredients to a user's pantry.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Verify the user exists
            cursor.execute('SELECT id FROM "user" WHERE id = %s', (user_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail=f"User with id {user_id} not found")

            # Insert ingredients (ignore duplicates)
            added_count = 0
            for ingredient_id in ingredient_ids:
                cursor.execute(
                    """
                    INSERT INTO user_ingredient (user_id, ingredient_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING;
                    """,
                    (user_id, ingredient_id)
                )
                if cursor.rowcount > 0:
                    added_count += 1

            conn.commit()

            return {
                "status": "success",
                "added_count": added_count,
                "total_requested": len(ingredient_ids)
            }

    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        conn.close()

