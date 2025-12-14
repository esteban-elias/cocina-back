'''
todo:
- Handle duplication
- Handle nullability
'''
from dotenv import load_dotenv
import json
import random
import re
import requests
import time
import psycopg2
from psycopg2 import OperationalError
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

def test_connection():
    """Test PostgreSQL database connection."""
    try:
        # Connection parameters
        connection = psycopg2.connect(
            host="localhost",
            database="cocina",
            user="s7",
            password="123456"
        )

        cursor = connection.cursor()

        cursor.execute("SELECT version();")
        db_version = cursor.fetchone()[0]

        print("✓ Connection successful!")
        print(f"PostgreSQL version: {db_version}")

        cursor.close()
        connection.close()

    except OperationalError as e:
        print(f"✗ Connection failed: {e}")


def create_tables():
    """Create database tables for the recipe application."""
    try:
        connection = psycopg2.connect(
            host="localhost",
            database="cocina",
            user="s7",
            password="123456"
        )

        cursor = connection.cursor()

        # Create ingredient table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ingredient (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE,
                name_es VARCHAR(255),
                img_url TEXT
            );
        """)

        # Create user table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS "user" (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE,
                device_id TEXT UNIQUE
            );
        """)

        # Create user_ingredient table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_ingredient (
                user_id INTEGER NOT NULL,
                ingredient_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, ingredient_id),
                FOREIGN KEY (user_id) REFERENCES "user"(id) ON DELETE CASCADE,
                FOREIGN KEY (ingredient_id) REFERENCES ingredient(id) ON DELETE CASCADE
            );
        """)

        # Create recipe table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recipe (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                name_es VARCHAR(255),
                minutes INTEGER NOT NULL,
                rating REAL,
                instructions TEXT NOT NULL,
                instructions_es TEXT,
                img_url TEXT,
                video_url TEXT
            );
        """)

        # Create recipe_ingredient junction table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recipe_ingredient (
                recipe_id INTEGER NOT NULL,
                ingredient_id INTEGER NOT NULL,
                PRIMARY KEY (recipe_id, ingredient_id),
                FOREIGN KEY (recipe_id) REFERENCES recipe(id) ON DELETE CASCADE,
                FOREIGN KEY (ingredient_id) REFERENCES ingredient(id) ON DELETE CASCADE
            );
        """)

        # Create product table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS product (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                price INTEGER NOT NULL,
                url TEXT NOT NULL,
                ingredient_id INTEGER,
                FOREIGN KEY (ingredient_id) REFERENCES ingredient(id) ON DELETE SET NULL
            );
        """)

        # Create product_click table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS product_click (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES "user"(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES product(id) ON DELETE CASCADE
            );
        """)

        connection.commit()
        print("✓ Tables created successfully!")

        cursor.close()
        connection.close()

    except OperationalError as e:
        print(f"✗ Error creating tables: {e}")


def load_ingredients():
    """Fetch ingredients from TheMealDB API and load into database."""
    try:
        # Fetch data from API
        url = "https://www.themealdb.com/api/json/v1/1/list.php?i=list"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        # Connect to database
        connection = psycopg2.connect(
            host="localhost",
            database="cocina",
            user="s7",
            password="123456"
        )

        cursor = connection.cursor()

        # Insert ingredients
        inserted_count = 0
        for meal in data['meals']:
            ingredient_name = meal['strIngredient']
            img_url = meal['strThumb']
            cursor.execute(
                "INSERT INTO ingredient (name, img_url) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING;",
                (ingredient_name, img_url)
            )
            if cursor.rowcount > 0:
                inserted_count += 1

        connection.commit()
        print(f"✓ Successfully loaded {inserted_count} ingredients!")

        cursor.close()
        connection.close()

    except requests.RequestException as e:
        print(f"✗ Error fetching data: {e}")
    except OperationalError as e:
        print(f"✗ Database error: {e}")


def load_recipes():
    """Fetch recipes from TheMealDB API and load into database."""
    try:
        # Connect to database
        connection = psycopg2.connect(
            host="localhost",
            database="cocina",
            user="s7",
            password="123456"
        )

        cursor = connection.cursor()

        # Load all ingredients into memory
        cursor.execute("SELECT id, name FROM ingredient;")
        ingredients = {name.strip().lower(): id for id, name in cursor.fetchall()}

        # Fetch recipes for each letter
        recipe_count = 0
        for letter in 'abcdefghijklmnopqrstuvwxyz':
            url = f"https://www.themealdb.com/api/json/v1/1/search.php?f={letter}"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            if not data['meals']:
                # todo: handle this error
                continue

            for meal in data['meals']:
                # Extract recipe data
                recipe_name = meal['strMeal']
                minutes = 0  # API doesn't provide cooking time
                rating = None  # API doesn't provide rating
                instructions = meal['strInstructions']
                img_url = meal['strMealThumb']
                video_url = meal['strYoutube']

                # Insert recipe
                cursor.execute(
                    """
                    INSERT INTO recipe (name, minutes, rating, instructions, img_url, video_url)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (recipe_name, minutes, rating, instructions, img_url, video_url)
                )
                recipe_id = cursor.fetchone()[0]

                # Extract and insert ingredients
                for i in range(1, 21):
                    ingredient = meal.get(f'strIngredient{i}', '')

                    ingredient_name = (ingredient or '').strip()
                    if not ingredient_name:
                        # todo: handle this error
                        continue

                    # Get ingredient ID
                    # todo: handle ID not found error
                    ingredient_key = ingredient_name.lower()
                    ingredient_id = ingredients.get(ingredient_key)

                    if ingredient_id:
                        # Insert recipe-ingredient relationship
                        cursor.execute(
                            """
                            INSERT INTO recipe_ingredient (recipe_id, ingredient_id)
                            VALUES (%s, %s)
                            ON CONFLICT DO NOTHING;
                            """,
                            (recipe_id, ingredient_id)
                        )

                recipe_count += 1

            print(f"✓ Processed recipes for letter '{letter}'")
            time.sleep(1)  # Be polite to the API

        connection.commit()
        print(f"✓ Successfully loaded {recipe_count} recipes!")

        cursor.close()
        connection.close()

    except requests.RequestException as e:
        print(f"✗ Error fetching data: {e}")
    except OperationalError as e:
        print(f"✗ Database error: {e}")


def load_products(markdown_file):
    """
    Load products from frutas-y-verduras.md file and match with ingredients using LLM.
    Example of markdown_file: 'data/frutas-y-verduras.md'
    todo:
     - Handle nullability
     - Proper clean, strips, replace, etc.
     - proper error handling
     - llm params
    """
    try:
        # Read the markdown file
        with open(markdown_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Connect to database
        connection = psycopg2.connect(
            host="localhost",
            database="cocina",
            user="s7",
            password="123456"
        )

        cursor = connection.cursor()

        # Load all ingredients into memory
        cursor.execute("SELECT id, name FROM ingredient;")
        ingredients = {name.lower(): id for id, name in cursor.fetchall()}

        products = []

        # # Extract product lines
        pattern = r'!\[([^\]]+)\].*?Agregar a Mis listas \$([0-9.,]+).*?\]\((https://www.jumbo.cl/[^\)]+)\)'
        matches = re.finditer(pattern, content, re.IGNORECASE)

        for index, match in enumerate(matches):
            # if index > 10:
                # continue

            product_name = match.group(1).strip().replace('\\', '')
            price_str = match.group(2).strip().replace('.', '')
            if not price_str.isdigit():
                continue
            price = int(price_str)
            url = match.group(3).strip()
            products.append({
                'name': product_name,
                'price': price,
                'url': url,
            })


        # Complete ingredient_id using LLM

        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0,
            max_tokens=None,  # Remove token limit or set much higher
            timeout=180,
            max_retries=3,
        )

        product_names = [{'name': product['name'], 'ingredient_id': '' } for product in products]

        messages = [
            (
                "system",
                """
- The user will provide you with a list of ingredients from a recipe database (in English) and a list of product names 
(in Spanish).
- Your task is to match each product name to the most relevant ingredient from the database.
- Return ONLY valid JSON list in this exact format: [{"name": "product1", "ingredient_id": 123}, ...]
- If no suitable match is found for a product, don't include that product in the returned list.
- Do not include any explanations, markdown formatting, or additional text.
                """,
            ),
            (
                "human",
                f"""
- Ingredients (format: name: id):
{ingredients}


- Products to match:
{product_names}
                """
            ),
        ]

        ai_msg = llm.invoke(messages)
        print(f"Response content length: {len(ai_msg.content)}\n")
        print(f"Response preview: {ai_msg.content[:500]}\n")
        
        if not ai_msg.content:
            print("⚠ Warning: Empty AI response. Check finish_reason in metadata.")
            print(f"Usage metadata: {ai_msg.usage_metadata if hasattr(ai_msg, 'usage_metadata') else 'N/A'}")
            return {'status': 'error', 'error': 'Empty AI response'}

        # Parse the LLM response
        import json
        matched_products = json.loads(ai_msg.content)
        
        # Create a lookup dictionary for matched products
        product_ingredient_map = {item['name']: item['ingredient_id'] for item in matched_products}
        
        # Insert products into database
        inserted_count = 0
        for product in products:
            ingredient_id = product_ingredient_map.get(product['name'])
            
            cursor.execute(
                """
                INSERT INTO product (name, price, url, ingredient_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING;
                """,
                (product['name'], product['price'], product['url'], ingredient_id)
            )
            if cursor.rowcount > 0:
                inserted_count += 1

        connection.commit()
        print(f"✓ Successfully loaded {inserted_count} products into database!")

        cursor.close()
        connection.close()

        return {
            'products_processed': len(products),
            'products_matched': len(matched_products),
            'products_inserted': inserted_count,
            'status': 'success'
        }

    except FileNotFoundError:
        error_msg = "✗ Error: frutas-y-verduras.md file not found"
        print(error_msg)
        return {'status': 'error', 'error': error_msg}
    except OperationalError as e:
        error_msg = f"✗ Database error: {e}"
        print(error_msg)
        return {'status': 'error', 'error': error_msg}
    except json.JSONDecodeError as e:
        error_msg = f"✗ Error parsing LLM response: {e}"
        print(error_msg)
        return {'status': 'error', 'error': error_msg}
    except Exception as e:
        error_msg = f"✗ Error: {e}"
        print(error_msg)
        return {'status': 'error', 'error': error_msg}


def merge_ingredients():
    """Merge duplicate ingredient names into their canonical entries."""
    replacements = {
        "Egg": "Eggs",
        "Onion": "Onions",
        "Oil": "Vegetable Oil",
        "Plain Flour": "Flour",
        "White Flour": "Flour",
        "All purpose flour": "Flour",
    }

    try:
        connection = psycopg2.connect(
            host="localhost",
            database="cocina",
            user="s7",
            password="123456"
        )

        cursor = connection.cursor()

        cursor.execute("SELECT id, name FROM ingredient;")
        ingredients = {name.lower(): id for id, name in cursor.fetchall()}

        for source, target in replacements.items():
            source_id = ingredients.get(source.lower())
            target_id = ingredients.get(target.lower())

            if not source_id:
                print(f"⚠ Skipping '{source}' -> '{target}': source not found")
                continue

            if not target_id:
                print(f"⚠ Skipping '{source}' -> '{target}': target not found")
                continue

            cursor.execute(
                """
                INSERT INTO recipe_ingredient (recipe_id, ingredient_id)
                SELECT recipe_id, %s FROM recipe_ingredient WHERE ingredient_id = %s
                ON CONFLICT DO NOTHING;
                """,
                (target_id, source_id)
            )

            cursor.execute(
                """
                INSERT INTO user_ingredient (user_id, ingredient_id)
                SELECT user_id, %s FROM user_ingredient WHERE ingredient_id = %s
                ON CONFLICT DO NOTHING;
                """,
                (target_id, source_id)
            )

            cursor.execute(
                """
                UPDATE product
                SET ingredient_id = %s
                WHERE ingredient_id = %s;
                """,
                (target_id, source_id)
            )

            cursor.execute("DELETE FROM ingredient WHERE id = %s;", (source_id,))
            print(f"✓ Merged '{source}' into '{target}'")

        connection.commit()
        print("✓ Ingredient unification complete!")

        cursor.close()
        connection.close()

    except OperationalError as e:
        print(f"✗ Database error: {e}")
    except Exception as e:
        print(f"✗ Error: {e}")


def translate_recipe_names():
    """Translate recipe names to Spanish and store them in name_es."""
    try:
        connection = psycopg2.connect(
            host="localhost",
            database="cocina",
            user="s7",
            password="123456"
        )

        cursor = connection.cursor()

        cursor.execute(
            """
            ALTER TABLE recipe
            ADD COLUMN IF NOT EXISTS name_es VARCHAR(255);
            """
        )

        cursor.execute(
            """
            SELECT id, name
            FROM recipe
            WHERE name_es IS NULL OR name_es = '';
            """
        )
        rows = cursor.fetchall()

        if not rows:
            print("✓ No recipes pending translation")
            cursor.close()
            connection.close()
            return

        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash-lite",
            temperature=0,
            timeout=180,
            max_retries=3,
        )

        batch_size = 100
        translated_count = 0

        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            payload = [{"id": row[0], "name": (row[1] or "").strip()} for row in batch if (row[1] or "").strip()]

            messages = [
                (
                    "system",
                    'Translate to Spanish. Return JSON like [{"id":1,"name_es":"..."}]. Nothing else.',
                ),
                (
                    "human",
                    json.dumps(payload, separators=(",", ":"))
                ),
            ]

            ai_msg = llm.invoke(messages)
            content = ai_msg.content.strip()
            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "").strip()
            elif content.startswith("```"):
                content = content.replace("```", "").strip()

            translations = json.loads(content)

            for item in translations:
                cursor.execute(
                    "UPDATE recipe SET name_es = %s WHERE id = %s;",
                    ((item.get("name_es") or "").strip(), item.get("id"))
                )
                if cursor.rowcount > 0:
                    translated_count += 1

            connection.commit()
            print(f"✓ Translated {len(translations)} recipe names")

        cursor.close()
        connection.close()
        print(f"✓ Completed recipe name translations: {translated_count} updates")

    except json.JSONDecodeError as e:
        print(f"✗ Error parsing LLM response: {e}")
    except OperationalError as e:
        print(f"✗ Database error: {e}")
    except Exception as e:
        print(f"✗ Error: {e}")


def translate_ingredient_names():
    """Translate ingredient names to Spanish and store them in name_es."""
    try:
        connection = psycopg2.connect(
            host="localhost",
            database="cocina",
            user="s7",
            password="123456"
        )

        cursor = connection.cursor()

        cursor.execute(
            """
            ALTER TABLE ingredient
            ADD COLUMN IF NOT EXISTS name_es VARCHAR(255);
            """
        )

        cursor.execute(
            """
            SELECT id, name
            FROM ingredient
            WHERE name_es IS NULL OR name_es = '';
            """
        )
        rows = cursor.fetchall()

        if not rows:
            print("✓ No ingredients pending translation")
            cursor.close()
            connection.close()
            return

        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash-lite",
            temperature=0,
            timeout=180,
            max_retries=3,
        )

        batch_size = 100
        translated_count = 0

        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            payload = [{"id": row[0], "name": (row[1] or "").strip()} for row in batch if (row[1] or "").strip()]

            messages = [
                (
                    "system",
                    'Translate ingredient names to Spanish. Return JSON like [{"id":1,"name_es":"..."}]. Nothing else.',
                ),
                (
                    "human",
                    json.dumps(payload, separators=(",", ":"))
                ),
            ]

            ai_msg = llm.invoke(messages)
            content = ai_msg.content.strip()
            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "").strip()
            elif content.startswith("```"):
                content = content.replace("```", "").strip()

            translations = json.loads(content)

            for item in translations:
                cursor.execute(
                    "UPDATE ingredient SET name_es = %s WHERE id = %s;",
                    ((item.get("name_es") or "").strip(), item.get("id"))
                )
                if cursor.rowcount > 0:
                    translated_count += 1

            connection.commit()
            print(f"✓ Translated {len(translations)} ingredients")

        cursor.close()
        connection.close()
        print(f"✓ Completed ingredient translations: {translated_count} updates")

    except json.JSONDecodeError as e:
        print(f"✗ Error parsing LLM response: {e}")
    except OperationalError as e:
        print(f"✗ Database error: {e}")
    except Exception as e:
        print(f"✗ Error: {e}")


def translate_recipe_instructions():
    """Translate recipe instructions to Spanish and store them in instructions_es."""
    try:
        connection = psycopg2.connect(
            host="localhost",
            database="cocina",
            user="s7",
            password="123456"
        )

        cursor = connection.cursor()

        cursor.execute(
            """
            ALTER TABLE recipe
            ADD COLUMN IF NOT EXISTS instructions_es TEXT;
            """
        )

        cursor.execute(
            """
            SELECT id, instructions
            FROM recipe
            WHERE (instructions_es IS NULL OR instructions_es = '')
              AND instructions IS NOT NULL;
            """
        )
        rows = cursor.fetchall()

        if not rows:
            print("✓ No recipe instructions pending translation")
            cursor.close()
            connection.close()
            return

        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash-lite",
            temperature=0,
            timeout=240,
            max_retries=3,
        )

        batch_size = 10
        translated_count = 0

        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            payload = [{"id": row[0], "instructions": (row[1] or "").strip()} for row in batch if (row[1] or "").strip()]

            messages = [
                (
                    "system",
                    'Translate recipe instructions to Spanish, keep steps/formatting. Return JSON like [{"id":1,"instructions_es":"..."}]. Nothing else.',
                ),
                (
                    "human",
                    json.dumps(payload, separators=(",", ":"))
                ),
            ]

            ai_msg = llm.invoke(messages)
            content = ai_msg.content.strip()
            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "").strip()
            elif content.startswith("```"):
                content = content.replace("```", "").strip()

            translations = json.loads(content)

            for item in translations:
                cursor.execute(
                    "UPDATE recipe SET instructions_es = %s WHERE id = %s;",
                    ((item.get("instructions_es") or "").strip(), item.get("id"))
                )
                if cursor.rowcount > 0:
                    translated_count += 1

            connection.commit()
            print(f"✓ Translated instructions for {len(translations)} recipes")

        cursor.close()
        connection.close()
        print(f"✓ Completed instruction translations: {translated_count} updates")

    except json.JSONDecodeError as e:
        print(f"✗ Error parsing LLM response: {e}")
    except OperationalError as e:
        print(f"✗ Database error: {e}")
    except Exception as e:
        print(f"✗ Error: {e}")


if __name__ == "__main__":
    # test_connection()
    # create_tables()
    # load_ingredients()
    # load_recipes()
    # load_products('data/lacteos-y-quesos.md')
    # merge_ingredients()
    # translate_recipe_names()
    # translate_ingredient_names()
    # translate_recipe_instructions()
